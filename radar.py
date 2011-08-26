#
# Proximate - Peer-to-peer social networking
#
# Copyright (c) 2008-2011 Nokia Corporation
#
# All rights reserved.
#
# This software is licensed under The Clear BSD license.
# See the LICENSE file for more details.
#
from gobject import timeout_add
import gtk
from math import pi, cos, sin, floor
from os.path import join

from community_gui import User_Action_List
from gui_user import get_user_profile_picture
from guiutils import pango_escape, GUI_Page
from pathname import get_dir, ICON_DIR
from plugins import Plugin, get_plugin_by_type
from support import debug, warning
from proximateprotocol import PLUGIN_TYPE_COMMUNITY, MAX_FACE_DIMENSION, \
    PROFILE_ICON_CHANGED
from guiutils import scale_image

PLUGIN_TYPE_RADAR = 'radar'

class UserRadar(gtk.DrawingArea):

    RING_COLORS = ['#333b4d', '#4a566f', '#99b3c1']
    RING_TEXT_COLORS = ['#000000', '#ffffff', '#ffffff']

    def __init__(self, main_gui):
        gtk.DrawingArea.__init__(self)
        self.set_events(gtk.gdk.ALL_EVENTS_MASK)
        self.connect('button-press-event', self.clicked)
        self.connect('expose-event', self.expose)
        self.context = None
        self.users = {} # user object : [face pixbuf, x, y, selected]
        self.drawn_users = [] # list of visible users on the radar
        self.selected_user = None
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        self.double_clicking = False
        self.main_gui = main_gui
        self.com = self.community.get_default_community()

    def set_community(self, com):
        self.com = com

    def set_double_clicking(self, value):
        self.double_clicking = value

    def clicked(self, widget, event, data=None):
        user = self.get_user_from_xy(event.x, event.y)
        if user:
            debug('radar: Clicked user %s\n' %(user.get('nick')))
            if user == self.selected_user and self.double_clicking:
                self.community.community_gui.show_user_page(user)
                # dehilight
                self.users[user][3] = False
            else:
                # hilight user and dehilight previous user
                if self.selected_user:
                    self.users[self.selected_user][3] = False
                self.selected_user = user
                self.users[self.selected_user][3] = True
                self.double_clicking = True
                timeout_add(500, self.set_double_clicking, False)
                self.queue_draw()
        else:
            debug('radar: Clicked %i, %i\n' %(event.x, event.y))
            self.set_double_clicking(False)
            # dehilight previous user
            if self.selected_user:
                self.users[self.selected_user][3] = False
            self.queue_draw()

    def expose(self, widget, event):
        self.context = widget.window.cairo_create()
        self.context.rectangle(event.area.x, event.area.y,
            event.area.width, event.area.height)
        self.context.clip()
        self.draw(self.context)
        return False

    def draw(self, context):
        rect = self.get_allocation()
        # shift origo
        o_x = rect.x + (rect.width / 2)
        o_y = rect.y + rect.height
        radius = min(rect.width / 2, rect.height) + (rect.width / 8)
        rings = [radius, radius*0.75, radius*0.5]

        # draw radar rings
        for ring, color in zip(rings, self.RING_COLORS):
            context.set_source_color(gtk.gdk.color_parse(color))
            context.arc(o_x, o_y, ring, pi, 2 * pi)
            context.fill()
        
        # draw user dots
        if not self.users:
            return
        self.drawn_users = []
        # split by hops
        drawable_users = self.community.get_community_members(self.com)
        user_hops = self.split_users_by_hops(drawable_users)
        for ring in xrange(len(user_hops)):
            hop_list = user_hops[ring]
            n = len(hop_list)
            if n == 0:
                continue
            hop_list.sort(cmp=self.compare_uids)
            if ring < 2: # rings start from 0
                a_start = (3*pi)/2 - (pi/2)*(1 - (2**-floor(n/2)))
                a_end = (3*pi)/2 + (pi/2)*(1 - (2**-floor(n/2)))
            else:
                a_start = (3*pi)/2 - (pi/4)*(1 - (2**-floor(n/2)))
                a_end = (3*pi)/2 + (pi/4)*(1 - (2**-floor(n/2)))
            if n == 1:
                d_a = 0
            else:
                d_a = (a_end - a_start)/(n-1)
            # rings are indexed backwards
            if ring == 0:
                r = rings[-1] * 0.75
            else:
                r = rings[-(1+ring)] - ((rings[-(1+ring)] - rings[-ring]) / 2)
            for i in xrange(len(hop_list)):
                user = hop_list[i]
                self.drawn_users.append(user)
                a = a_start + d_a*i
                user_x, user_y = self.polar_to_xy(r, a, o_x, o_y)
                self.users[user][1] = user_x
                self.users[user][2] = user_y
                # draw face
                num_users = len(hop_list)
                if num_users < 5:
                    scale_factor = 2
                elif num_users < 10:
                    scale_factor = 4
                else:
                    scale_factor = 8
                face = self.scale_user_face(user, scale_factor)
                user_selected = self.users[user][3]
                if user_selected:
                    face.saturate_and_pixelate(face, 2, 0)
                context.set_source_pixbuf(face, user_x - face.get_width() / 2,
                    user_y - face.get_height() / 2)
                context.rectangle(user_x - face.get_height() / 2,
                    user_y - face.get_height() / 2, face.get_width(),
                    face.get_height())
                context.fill()
                # show nick
                nick = user.get('nick')
                font_size = 12
                context.set_source_color(gtk.gdk.color_parse(self.RING_TEXT_COLORS[ring]))
                context.move_to(user_x - (face.get_width() / 2),
                    user_y + (face.get_height() / 2) + 12)
                context.set_font_size(font_size)
                context.show_text(nick)
                context.stroke()

                debug('radar: Drawing %s to (%i,%i)\n'
                    %(nick, user_x, user_y))

    def split_users_by_hops(self, users):
        # splits the "users" list into three lists by hops: 0 or 1, 2 and >3
        one = []
        two = []
        three = []
        for user in users:
            hops = user.get('hops')
            if hops == 0 or hops == 1 or hops == None:
                one.append(user)
            elif hops == 2:
                two.append(user)
            elif hops > 2:
                three.append(user)
        return (one, two, three)

    def compare_uids(self, user_a, user_b):
        uid_a = int(user_a.get('uid'), 16)
        uid_b = int(user_b.get('uid'), 16)
        if uid_a < uid_b:
            return -1
        elif uid_a == uid_b:
            return 0
        else:
            return 1

    def polar_to_xy(self, r, a, o_x, o_y):
        # from polar to cartesian coordinates
        # r: radius, a: angle, o_x, o_y: coordinates for origo
        x = int(r*cos(a) + o_x)
        y = int(r*sin(a) + o_y)
        return (x, y)

    def new_user(self, user):
        # adds user to list, creates a small profile picture
        # and redraws the radar view
        image = self.scale_user_face(user, 2)
        self.users[user] = [image, 0, 0, False]
        self.queue_draw()

    def update_user(self, user, what):
        # updates users profile picture if it's changed
        # and redraws the radar view
        if what and what[0] == PROFILE_ICON_CHANGED:
            debug('radar: User changed profile picture\n')
            if user in self.users:
                self.users[user][0] = self.scale_user_face(user, 2)
        self.queue_draw()

    def remove_user(self, user):
        # removes user and redraws the radar view
        if user == self.selected_user:
            self.selected_user = None
        self.users.pop(user)
        self.queue_draw()

    def scale_user_face(self, user, factor):
        # returns saved face picture if user is in dictionary,
        # else creates a new picture, and saves and returns it
        return scale_image(get_user_profile_picture(
            user, status_icons=False, center=False), MAX_FACE_DIMENSION / factor)

    def get_user_from_xy(self, x, y):
        # Select the front most user. The user list is sorted in
        # "back to front" order.
        for user in reversed(self.drawn_users):
            triple = self.users.get(user)
            if triple == None:
                continue
            face, user_x, user_y, _ = triple
            if x > user_x - face.get_width() / 2 and \
                x < user_x + face.get_width() / 2 and \
                y > user_y - face.get_height() / 2 and \
                y < user_y + face.get_height():
               return user
        return None

    def get_selected(self):
        if self.selected_user:
            user = self.selected_user
            self.users[self.selected_user][3] = False
            self.selected_user = None
            return user
        return self.community.get_default_community()

class Radar_Plugin(Plugin):
    def __init__(self, main_gui):
        self.register_plugin(PLUGIN_TYPE_RADAR)
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        self.myself = self.community.get_myself()
        self.main_gui = main_gui

        self.page = GUI_Page('Radar')
        self.user_radar = UserRadar(main_gui)
        self.page.pack_start(self.user_radar)
        self.action_list = User_Action_List(self.community.community_gui,
            self.user_radar.get_selected)
        self.page.pack_start(self.action_list.get_widget(), False, True)
        self.page.show_all()
        self.main_gui.add_page(self.page)
    
        # Press 'r' to switch to radar view
        self.main_gui.add_key_binding(gtk.gdk.CONTROL_MASK, gtk.keysyms.r, self.key_pressed_r)

        self.radar_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR),
            'radar.png'))
        self.main_gui.add_statusbar_icon(self.radar_icon, 'Open radar',
            self.statusbar_icon_clicked)

    def key_pressed_r(self, target, ctx):
        self.run()

    def statusbar_icon_clicked(self):
        if self.page.is_visible:
            self.main_gui.hide_page(self.page)
        else:
            self.run()

    def run(self):
        # get the last opened community from the main gui
        open_community = self.community.get_default_community()
        for page in reversed(self.main_gui.page_history):
            com = page.get_community()
            if com != None:
                open_community = com
                break
        cname = open_community.get('name')
        debug('radar: Opening radar view for community %s\n' % cname)
        self.page.set_page_title(cname, sub=True)
        self.user_radar.set_community(open_community)
        self.main_gui.show_page(self.page)

    def user_appears(self, user):
        if user != self.myself and self.main_gui:
            self.user_radar.new_user(user)

    def user_changes(self, user, what=None):
        if user != self.myself and self.main_gui:
            self.user_radar.update_user(user, what)

    def user_disappears(self, user):
        if user != self.myself and self.main_gui:
            self.user_radar.remove_user(user)

def init_ui(main_gui):
    Radar_Plugin(main_gui)
