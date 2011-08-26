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
import gtk
import gobject

import proximatestate
from plugins import get_plugin_by_type
from support import get_debug_mode
from os.path import join
from pathname import get_dir, get_path, ICON_DIR, DEFAULT_COMMUNITY_ICON, \
    DEFAULT_USER_ICON, SMALL_KEYS_ICON, PROXIMATE_COMMUNITY_ICON
from proximateprotocol import PLUGIN_TYPE_COMMUNITY, PLUGIN_TYPE_KEY_MANAGEMENT, \
     PLUGIN_TYPE_STATE, MAX_FACE_DIMENSION, DEFAULT_COMMUNITY_NAME
from pic_choose_dlg import Picture_Choose_Dialog
from proximateprotocol import PLUGIN_TYPE_NOTIFICATION, valid_status
from guiutils import GUI_Page, Action_List, center_image, add_icon_to_image, \
    new_scrollarea, pango_escape
from utils import str_to_int

ACTION_IMAGE_SIZE = 48

def get_status_icon(status, size):
    if not valid_status(status):
        status = 'normal'
    fname = '%dpx-status_icon_%s.png' % (size, status)
    return gtk.gdk.pixbuf_new_from_file_at_size(join(get_dir(ICON_DIR), fname), size, size)

# descriptive names for all profile fields
field_descriptions = {
    'name': 'Name',
    'age': 'Age',
    'gender': 'Gender',
    'city': 'City',
    'state': 'State',
    'country': 'Country',
    'birth_date': 'Birth Date',
    'email': 'E-mail',
    'www': 'WWW',
    'occupation': 'Occupation',
    'phone_numbers': 'Phone Numbers',
    'languages': 'Languages',
    'description': 'Description',
    'uid': 'uid',
    'ip': 'IP',
    'port': 'Port',
    'hops': 'Hops',
    'status_icon': 'Status icon',
    'v': 'Version',
    'faceversion': 'Face version',
    'myfaceversion': 'My face version',
}

class User_Page(GUI_Page):

    def __init__(self, gui, community_gui, user):
        """User_Page class is for showing user's profile information
        defined in the Edit Profile dialog and for showing user's
        communities.

        update_user_page() have to be called after user's profile
        is changed or after user's communities are changed so that
        new values are loaded into GUI"""

        GUI_Page.__init__(self, user.get('nick'))

        self.main_gui = gui
        self.community_gui = community_gui
        self.user = user

        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        self.state_plugin = get_plugin_by_type(PLUGIN_TYPE_STATE)

        self.notebook = gtk.Notebook()
        self.notebook.set_show_tabs(True)
        self.notebook.set_show_border(False)
        self.initialize_profile_page()
        self.initialize_user_action_page()
        self.initialize_communities_page()
        self.pack_start(self.notebook)

        self.show_all()

    def get_user(self):
        return self.user

    def back_action(self):
        self.community_gui.user_pages.pop(self.user)
        self.main_gui.remove_page(self)
        self.destroy()
        return True

    def update_user_page(self):
        """ Function calls other functions to update user's
        profile, community, content and plugin pages. """

        self.update_profile_widgets()
        self.set_page_title(self.user.get('nick'))

    def initialize_user_action_page(self):
        vbox = gtk.VBox()

        add_user_icon = gtk.gdk.pixbuf_new_from_file_at_size(join(get_dir(ICON_DIR), "64px-plus_icon.png"), ACTION_IMAGE_SIZE, ACTION_IMAGE_SIZE)
        remove_user_icon = gtk.gdk.pixbuf_new_from_file_at_size(join(get_dir(ICON_DIR), "64px-no_icon.png"), ACTION_IMAGE_SIZE, ACTION_IMAGE_SIZE)
        exchange_keys_icon = gtk.gdk.pixbuf_new_from_file_at_size(join(get_dir(ICON_DIR), "key.png"), ACTION_IMAGE_SIZE, ACTION_IMAGE_SIZE)
        refetch_icon =  gtk.gdk.pixbuf_new_from_file_at_size(join(get_dir(ICON_DIR), "64px-edit_metadata_icon.png"), ACTION_IMAGE_SIZE, ACTION_IMAGE_SIZE)

        action_buttons = [(add_user_icon, 'Invite to\nCommunity', self.show_invite_dialog_cb),
                          (refetch_icon, 'Refetch\nProfile', self.refetch_profile_cb),
                         ]
        if self.state_plugin.options.personal_communities:
            action_buttons.insert(0, (add_user_icon, 'Add to\n Community',
                self.show_add_dialog_cb))
            action_buttons.insert(1, (remove_user_icon, 'Remove from\nCommunity',
                self.show_remove_dialog_cb))

        if self.state_plugin.options.key_exchange:
            action_buttons.insert(3, (exchange_keys_icon, 'Exchange\nKeys', self.show_exchange_keys_dialog_cb))

        self.actions = Action_List()

        for action in action_buttons:
            (icon, text, cb) = action
            self.actions.add_button(icon, text, cb)

        vbox.pack_start(self.actions.get_widget())

        self.announce_checkbox = gtk.CheckButton('Make an alarm when user appears')
        vbox.pack_start(self.announce_checkbox, False, False)
        self.announce_checkbox.set_active(self.user.get('friend'))
        self.announce_checkbox.connect('toggled', self.set_announce)

        self.notebook.append_page(vbox, gtk.Label('More actions'))

    def initialize_profile_page(self):
        
        profile_hbox = gtk.HBox()
        vbox = gtk.VBox()

        picture_hbox = gtk.HBox()
        self.profile_image = gtk.Image()
        self.profile_image.set_size_request(MAX_FACE_DIMENSION+10, MAX_FACE_DIMENSION+10)
        picture_hbox.pack_start(self.profile_image, False, True)
        self.status_label = gtk.Label()
        self.status_label.set_line_wrap(True)
        picture_hbox.pack_start(self.status_label)
        vbox.pack_start(picture_hbox)

        self.profile_info_label = gtk.Label()
        self.profile_info_label.set_alignment(0.1, 0.01) # 0.01 on purpose
        self.profile_info_label.set_line_wrap(True)
        vbox.pack_start(self.profile_info_label)

        profile_hbox.pack_start(vbox)

        self.user_action_list = User_Action_List(self.community_gui,
            self.get_user)
        profile_hbox.pack_start(self.user_action_list.action_view)

        swindow = new_scrollarea()
        swindow.set_border_width(0)
        swindow.add_with_viewport(profile_hbox)

        self.update_profile_widgets()

        self.notebook.append_page(swindow, gtk.Label('Profile'))

    def initialize_communities_page(self):
        vbox = gtk.VBox()

        self.list = Community_List(self.view_community)
        for com in self.community.get_user_communities(self.user):
            self.list.add_community(com)
        vbox.pack_start(self.list.get_widget())

        self.notebook.append_page(vbox, gtk.Label('User communities'))

    def view_community(self, com):
        self.community_gui.show_com_page(com)

    def update_profile_widgets(self):
        """ Reads new profile information from user and
        updates profile page's widgets."""
        image = get_user_profile_picture(self.user)
        if not self.user.present:
            image.saturate_and_pixelate(image, 0.0, True)
        self.profile_image.set_from_pixbuf(image)
        value = self.user.get('status')
        if value == None:
            value = ''
        self.status_label.set_text(value)
        self.profile_info_label.set_markup(self.construct_profile_info_str())

    def construct_profile_info_str(self):

        def heading(s):
            # Returns a heading string s formatted with pango markup and
            # a new-line
            return '<span color="slategray" weight="bold" size="large">%s</span>\n' % pango_escape(s)

        def field(s):
            value = self.user.get(s)
            if value != None:
                return '<b>%s:</b> %s\n' % (field_descriptions[s], pango_escape(str(value)))
            else:
                return ''

        def join_list(l):
            out = []
            for s in l:
                value = self.user.get(s)
                if value != None:
                    out.append(pango_escape(str(value)))
            if len(out) > 0:
                return ', '.join(out) + '\n'
            else:
                return ''

        s = heading(self.user.get('nick'))
        s += field('name')

        s += join_list(('age', 'gender'))
        s += field('birth_date')

        s += join_list(('city', 'state', 'country'))

        s += field('phone_numbers')
        s += field('email')
        s += field('www')

        s += field('occupation')
        s += field('languages')

        s += field('description')

        s += heading('Last contact')
        l = []
        for (t, location) in self.user.log():
            ss = t
            if len(location) > 0:
                ss += '\n(at %s)' %(location)
            l.append(ss)
        if len(l) == 0:
            l = ['never']
        s += pango_escape('\n'.join(l)) + '\n'

        if get_debug_mode():
            s += heading('Debug information')
            s += field('uid')
            s += field('ip')
            s += field('port')
            s += field('hops')
            s += field('status_icon')
            s += field('v')
            s += field('faceversion')
            s += field('myfaceversion')

        return s

    def show_add_dialog_cb(self, widget):
        Add_To_Community_Dialog(self.main_gui, self.user)

    def show_invite_dialog_cb(self, widget):
        Invite_To_Community_Dialog(self.main_gui, self.user)
        
    def show_remove_dialog_cb(self, widget):
        Remove_From_Community_Dialog(self.main_gui, self.user)
  
    def show_exchange_keys_dialog_cb(self, widget):
        keymanagement = get_plugin_by_type(PLUGIN_TYPE_KEY_MANAGEMENT)
        keymanagement.show_exchange_keys_gui(self.user)

    def refetch_profile_cb(self, widget):
        self.user.force_profile_update()
        notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)
        notification.notify('Reloading profile for %s' %(self.user.tag()))

    def set_announce(self, widget):
        self.user.set('friend', widget.get_active())

class My_User_Page(GUI_Page):

    def __init__(self, gui, user):
        """User_Page class is for showing user's profile information
        defined in the Edit Profile dialog and for showing user's
        communities.

        update_user_page() have to be called after user's profile
        is changed or after user's communities are changed so that
        new values are loaded into GUI"""

        GUI_Page.__init__(self, 'My profile')
        # references to gui components which text or other
        # attribute will be modified if user's profile changes
        self.profile_widgets = {}

        self.main_gui = gui
        self.user = user

        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)

        self.initialize_profile_page_widgets()

        self.pic_dialog = Picture_Choose_Dialog(self.main_gui, self.got_picture)

    def update_user_page(self):
        """ Function calls other functions to update user's
        profile, community, content and plugin pages. """

        self.update_profile_widgets()
        
    def update_profile_widgets(self):
        """ Reads new profile information from user and
        updates profile page's widgets."""
        
        image = get_user_profile_picture(self.user)
        self.profile_image.set_from_pixbuf(image)

    def initialize_profile_page_widgets(self):
        
        self.profile_main_vbox = gtk.VBox()
        swindow = new_scrollarea()
        swindow.set_border_width(0)

        main_hbox = gtk.HBox(False, 20)

        picture_vbox = gtk.VBox()

        self.profile_image = gtk.Image()
        self.profile_image.set_size_request(MAX_FACE_DIMENSION+10, MAX_FACE_DIMENSION+10)

        eventbox = gtk.EventBox()
        eventbox.connect("button-press-event", self.image_clicked)
        eventbox.add(self.profile_image)
        picture_vbox.pack_start(gtk.Label('Click picture to change'))
        picture_vbox.pack_start(eventbox, True, True)

        # User always has a nick
        widget = gtk.Entry()
        widget.set_text(self.user.get('nick'))
        widget.connect("focus-out-event", self.entry_focus_out, 'nick')
        self.profile_widgets['nick'] = widget
        nick_label = gtk.Label('Nick:')
        nick_label.set_alignment(0, 0)
        picture_vbox.pack_start(nick_label, False, False)
        picture_vbox.pack_start(widget, False, False)

        left_hbox = gtk.VBox(False, 20)
        left_hbox.pack_start(picture_vbox, False, False)

        user_info_vbox = gtk.VBox(False, 5)

        profile_components = (('Name:', 'name'),
                              ('Age:', 'age'),
                              ('Gender:', 'gender'),
                              ('City:', 'city'),
                              ('State:', 'state'),
                              ('Country:', 'country'),
                              ('Birth Date:', 'birth_date'),
                              ('E-mail:', 'email'),
                              ('WWW:', 'www'),
                              ('Occupation:', 'occupation'),
                              ('Phone Numbers:', 'phone_numbers'),
                              ('Languages:', 'languages'),
                              ('Description:', 'description'),
                             )

        genders = ('Male', 'Female')

        for header, key in profile_components:
            hbox = gtk.HBox()
            label = gtk.Label(header)
            label.set_size_request(130, -1)
            label.set_alignment(0, 0)

            value = self.user.get(key)
            if value == None:
                value = ''

            if key == 'gender':
                # create gender widget separately
                widget = gtk.combo_box_entry_new_text()
                for gender in genders:
                    widget.append_text(gender)
                entry = widget.child
                entry.set_text(str(value))

                widget.connect("changed", self.combo_changed, key)
            elif key == 'description':
                widget = gtk.TextView()
                widget.get_buffer().set_text(str(value))
                widget.set_property("wrap-mode", gtk.WRAP_CHAR)
                widget.set_size_request(-1, 100)
                entry = widget
            else:
                widget = gtk.Entry()
                widget.set_text(str(value))
                entry = widget

            entry.connect("focus-out-event", self.entry_focus_out, key)

            hbox.pack_start(label, False, False)
            hbox.pack_start(widget, True, True)

            self.profile_widgets[key] = entry
            user_info_vbox.pack_start(hbox, False, False)

        main_hbox.pack_start(left_hbox, False, False)
        main_hbox.pack_start(user_info_vbox, True, True)

        swindow.add_with_viewport(main_hbox)

        self.update_profile_widgets()

        self.pack_start(swindow, True, True)

    def image_clicked(self, widget, event):
        self.pic_dialog.set_picture(proximatestate.seek_face_name(self.user))
        self.pic_dialog.show()

    def got_picture(self, fname):
        self.community.set_my_face(fname)

    def combo_changed(self, widget, key):
        self.entry_focus_out(widget.child, None, key)

    def entry_focus_out(self, entry, event, key):
        if key == 'description':
            buf = entry.get_buffer()
            value = buf.get_text(buf.get_start_iter(), buf.get_end_iter())
        else:
            value = entry.get_text()
        if len(value) == 0:
            value = None
        if value != self.user.get(key):
            if self.user.set(key, value):
                self.community.announce_user_change(self.user, allowme=True)
            else:
                # re-insert old value if set fails
                value = self.user.get(key)
                if value == None:
                    value = ''
                entry.set_text(str(value))

class Community_List:
    COL_ICON = 0
    COL_NAME = 1
    COL_MEMBERS = 2
    COL_DESC = 3
    COL_COM = 4

    def __init__(self, activate_cb=None):
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)

        self.store = gtk.ListStore(gtk.gdk.Pixbuf, str, str, str, object)

        self.scrollarea = new_scrollarea()
        self.scrollarea.set_size_request(-1, 340)
        self.view = gtk.TreeView()
        self.view.set_headers_visible(True)

        cr1 = gtk.CellRendererPixbuf()
        cr2 = gtk.CellRendererText()
        cr3 = gtk.CellRendererText()
        cr4 = gtk.CellRendererText()
        cr3.set_property('xalign', 0.1)

        col = gtk.TreeViewColumn('Community')
        col.pack_start(cr1, False)
        col.pack_start(cr2)
        col.add_attribute(cr1, 'pixbuf', self.COL_ICON)
        col.add_attribute(cr2, 'text', self.COL_NAME)

        col2 = gtk.TreeViewColumn('Members')
        col2.pack_start(cr3)
        col2.add_attribute(cr3, 'text', self.COL_MEMBERS)

        self.column_desc = gtk.TreeViewColumn('Description')
        self.column_desc.pack_start(cr4)
        self.column_desc.add_attribute(cr4, 'text', self.COL_DESC)

        self.view.append_column(col)
        self.view.append_column(col2)
        self.view.append_column(self.column_desc)

        self.view.set_model(self.store)
        self.view.connect('row-activated', self.row_activated_cb)
        self.view.connect_after('size-allocate', self.resized)

        self.activated = activate_cb

        self.scrollarea.add_with_viewport(self.view)

    def get_widget(self):
        return self.scrollarea

    def add_community(self, c):
        n = len(self.community.get_community_members(c))
        myself = self.community.get_myself()
        if c in self.community.get_user_communities(myself):
            n += 1
        icon = get_community_icon(c).scale_simple(48, 48, gtk.gdk.INTERP_BILINEAR)
        desc = c.get('description')
        if desc == None:
            desc = ''
        desc = desc.replace('\n', ' ')
        if n == 0:
            icon.saturate_and_pixelate(icon, 0.0, True)
            self.store.append([icon, c.get('name'), str(n), desc, c])
        else:
            self.store.prepend([icon, c.get('name'), str(n), desc, c])

    def get_selected(self):
        model, selected = self.view.get_selection().get_selected_rows()
        if len(selected) == 0:
            return None
        row = self.store[selected[0]]
        return row[self.COL_COM]

    def row_activated_cb(self, treeview, path, col):
        store = treeview.get_model()
        row = store[path]
        com = row[self.COL_COM]
        if self.activated != None:
            self.activated(com)

    def resized(self, view, rect):
        columns_width = 0
        for col in view.get_columns():
            if col != self.column_desc:
                columns_width += col.get_width()
        if rect.width < columns_width:
            return
        wrap_width = rect.width - columns_width
        self.column_desc.get_cell_renderers()[0].set_property('wrap-width', wrap_width)
        self.column_desc.set_property('max-width', wrap_width)

        store = view.get_model()
        i = store.get_iter_first()
        while i and store.iter_is_valid(i):
                store.row_changed(store.get_path(i), i)
                i = store.iter_next(i)
                view.set_size_request(0, -1)

class Community_List_Dialog:
    def __init__(self, gui, title, actiontext=gtk.STOCK_OK):
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        self.notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)

        self.main_window = gui.get_main_window()
        self.dialog = gtk.Dialog(title, self.main_window, gtk.DIALOG_DESTROY_WITH_PARENT,
                                 (actiontext, gtk.RESPONSE_OK,
                                  gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL))
        self.dialog.set_modal(True)

        self.list = Community_List()
        self.dialog.vbox.pack_start(self.list.get_widget(), True, True)
        self.dialog.connect("response", self.response_handler)
        self.dialog.set_default_size(400, 300)
        self.dialog.show_all()

    def add_community(self, com):
        self.list.add_community(com)

    def response_handler(self, widget, event):
        if event == gtk.RESPONSE_OK:
            com = self.list.get_selected()
            if com != None:
                self.community_selected(com)

        self.dialog.destroy()

class Add_To_Community_Dialog(Community_List_Dialog):
    def __init__(self, gui, user):
        Community_List_Dialog.__init__(self, gui, 'Add User To Community', actiontext='Add')

        self.user = user

        communities = self.community.find_communities(None, False, None)
        usercoms = self.community.get_user_personal_communities(self.user)
        for com in communities:
            if not self.community.personal_communities and com.get('peer') == False:
                continue
            if not com in usercoms:
                self.add_community(com)

    def community_selected(self, com):
        self.community.add_member(com, self.user)

class Invite_To_Community_Dialog(Community_List_Dialog):
    def __init__(self, gui, user):
        Community_List_Dialog.__init__(self, gui, 'Invite User To Community', actiontext='Invite')

        self.user = user

        myself = self.community.get_myself()
        communities = self.community.get_user_communities(myself)
        usercoms = self.community.get_user_communities(self.user)
        for com in communities:
            if not com in usercoms:
                self.add_community(com)

    def community_selected(self, com):
        if not self.community.invite_member(com, self.user, self.invite_sent):
            self.notification.notify('Unable to send an invitation to %s' % self.user.tag(), True)

    def invite_sent(self, success):
        if not success:
            self.notification.notify('Unable to send an invitation to %s' % self.user.tag(), True)

class Remove_From_Community_Dialog(Community_List_Dialog):
    def __init__(self, gui, user):
        Community_List_Dialog.__init__(self, gui, 'Remove User From Community', actiontext='Remove')

        self.user = user

        communities = self.community.get_user_personal_communities(self.user)
        for com in communities:
            self.add_community(com)

    def community_selected(self, com):
        self.community.remove_member(com, self.user)

class User_Action_List(Action_List):
    def __init__(self, gui, get_selected_func):
        Action_List.__init__(self)
        self.get_selected = get_selected_func
        self.community_gui = gui
        for event in self.community_gui.user_events:
            self.add_event(event)
        self.community_gui.register_user_action_list(self)

    def add_event(self, event):
        (icon, name, callback) = event
        self.add_button(icon, name, self.action, callback)

    def action(self, callback):
        callback(self.get_selected())

def get_default_community_icon(com):
    if com == proximatestate.get_ordinary_community(DEFAULT_COMMUNITY_NAME):
        fname = get_path(PROXIMATE_COMMUNITY_ICON)
    else:
        fname = get_path(DEFAULT_COMMUNITY_ICON)
    return gtk.gdk.pixbuf_new_from_file(fname)

def get_community_icon(com):
    fname = proximatestate.seek_community_icon_name(com)
    try:
        com_icon = gtk.gdk.pixbuf_new_from_file(fname)
    except gobject.GError:
        # if we have broken community information (picture missing)
        # we must use default icon
        com_icon = get_default_community_icon(com)
    return com_icon

def create_default_user_picture(user):
    # list of suitable colors to pick from
    colors = (0x000000FF, 0x8A8A8AFF, 0x9B00AFFF, 0x5DAF00FF,
        0x79AF00FF, 0xA8AF00FF, 0xAF9B00FF, 0xAF6000FF,
        0xAF0016FF, 0xAF0092FF, 0xBC0086FF, 0x000FBCFF,
        0x007403FF, 0x007466FF, 0xD5FFBAFF, 0xFFFFFFFF)

    # use default icon and color it using the first char as an index
    buf = gtk.gdk.pixbuf_new_from_file(get_path(DEFAULT_USER_ICON))
    icon = buf.copy()
    color = colors[int(user.get('uid')[0], 16)]
    icon.fill(color)
    buf.composite(icon, 0, 0, buf.get_width(), buf.get_height(),
        0, 0, 1.0, 1.0, gtk.gdk.INTERP_NEAREST, 255)

    return icon

def get_user_profile_picture(user, status_icons=True, center=True):
    """ Returns picture saved in user's profile as a GDK Pixbuf,
        or the default picture with a background color
        generated from uid.
        Status icons are added to the picture, if status_icons == True.
        """
    try:
        icon = gtk.gdk.pixbuf_new_from_file(proximatestate.seek_face_name(user))
    except gobject.GError:
        icon = create_default_user_picture(user)

    if center:
        # center image if it's smaller than MAX_FACE_DIMENSION
        smaller_dimension = min(icon.get_width(), icon.get_height())
        if smaller_dimension < MAX_FACE_DIMENSION:
            icon = center_image(icon, MAX_FACE_DIMENSION, MAX_FACE_DIMENSION)

    if status_icons:
        # add small status icons
        community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        if not user == community.get_myself():
            if user.get('key_fname'):
                status_icon = gtk.gdk.pixbuf_new_from_file(get_path(SMALL_KEYS_ICON))
                add_icon_to_image(icon, status_icon, 4)

        user_status = user.get('status_icon')
        if user_status:
            add_icon_to_image(icon, get_status_icon(user_status, 32), 0)

    return icon
