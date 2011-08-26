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
import time

# Hildon is optional
from guiutils import have_hildon
if have_hildon:
    import hildon

from gui_user import get_user_profile_picture, get_community_icon, \
     get_status_icon, My_User_Page, User_Page, User_Action_List, \
     Community_List_Dialog, get_default_community_icon
from plugins import get_plugin_by_type
from os.path import join
from pathname import get_dir, get_path, ICON_DIR, DEFAULT_COMMUNITY_ICON
from support import warning, get_debug_mode
from proximateprotocol import PLUGIN_TYPE_COMMUNITY, PLUGIN_TYPE_NOTIFICATION, \
    valid_community, USER_STATUS_LIST, MAX_FACE_DIMENSION, PLUGIN_TYPE_SETTINGS
from general_dialogs import Approve_Deny_Dialog
from proximatestate import seek_community_icon_name
from pic_choose_dlg import Picture_Choose_Dialog
from guiutils import GUI_Page, Action_List, new_scrollarea, pango_escape
from guihandler import STATUSBAR_ICON_SIZE

# descriptive names for all community profile fields
field_descriptions = {
    'name': 'Name',
    'location': 'Location',
    'www': 'WWW',
    'description': 'Description',
    'v': 'Version',
    'iconversion': 'Icon version',
    'myiconversion': 'My icon version',
}

class Community_GUI(GUI_Page):
    """ This class is used for loading community management GUI functionalities into
    main GUI.

    The class is initialized by guihandler before all main GUI parts are initialized.
    """

    COMMUNITY_ICON = '64px-community_mgmt_icon.png'
    COL_ICON = 0
    COL_COM = 1
    COL_NAME = 2

    def __init__(self, gui):
        GUI_Page.__init__(self, 'Home')
        self.main_gui = gui

        self.notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)

        # store User_Page instances key = user
        self.user_pages = {}

        # store Community_Page instances key = community
        self.com_pages = {}

        self.com_events = []
        self.user_events = []
        self.user_action_lists = []
        self.com_action_lists = []

        self.item_double_clicking = None

        self.initialize_menu()

        icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), self.COMMUNITY_ICON))
        self.com_events.append((icon, "Community", self.manage_community_cb))

        self.itemlist = gtk.ListStore(gtk.gdk.Pixbuf, gobject.TYPE_PYOBJECT, str)
        self.update_communities()

        self.initialize_item_list()
        self.action_list = Community_Action_List(self, self.get_selected)
        self.pack_start(self.action_list.get_widget(), False, True)

        self.show_all()
        gui.add_page(self)
        gui.show_page(self)

        myself = self.community.get_myself()

        page = My_User_Page(gui, myself)
        self.user_pages[myself] = page
        page.show_all()
        gui.add_page(page)

        status_icon_pic = get_status_icon(myself.get('status_icon'), STATUSBAR_ICON_SIZE)
        self.status_icon = gui.add_statusbar_icon(status_icon_pic, 'Change status', self.status_icon_clicked)

        settings = get_plugin_by_type(PLUGIN_TYPE_SETTINGS)
        self.list_view_setting = settings.register('community.list_view', bool, 'Display community members as a list', default=False)

        self.community.register_ui(self)

    def back_action(self):
        if have_hildon:
            self.main_gui.close_proximate(None)
        return True

    def initialize_item_list(self):
        vbox = gtk.VBox()

        self.itemview = gtk.IconView(self.itemlist)

        self.itemview.set_spacing(6)
        self.itemview.set_row_spacing(9)
        self.itemview.connect('item-activated', self.handle_item_clicked)
        self.itemview.connect('button-press-event', self.view_clicked, None)

        self.itemview.set_pixbuf_column(self.COL_ICON)
        self.itemview.set_text_column(self.COL_NAME)

        swindow = new_scrollarea()
        swindow.add_with_viewport(self.itemview)

        vbox.pack_start(swindow)

        self.pack_start(vbox, True, True)

    def handle_item_clicked(self, view, path):
        row = self.itemlist[path]
        com = row[1]
        self.show_com_page(com)

    def view_clicked(self, iconview, event, param):
        if event.type == gtk.gdk.BUTTON_PRESS and event.button == 1:
            coords = event.get_coords()
            if coords == ():
                return
            (x,y) = coords

            # simulate double click with a timeout variable
            if not self.item_double_clicking:
                self.set_item_double_clicking(True)
                timeout_id = gobject.timeout_add(500, self.set_item_double_clicking, False)
                return

            path = iconview.get_path_at_pos(int(x), int(y))
            if path != None:
                # is the item already selected
                selected = iconview.path_is_selected(path)
                if selected:
                    self.handle_item_clicked(iconview, path)

    def set_item_double_clicking(self, doubleclick):
        self.item_double_clicking = doubleclick
        return False # timeout shouldn't call this again

    def get_selected(self):
        selected = self.itemview.get_selected_items()
        if len(selected) > 0:
            path = selected[0] # there should be 0 or 1 selected items
            row = self.itemlist[path]
            value = row[self.COL_COM]
        else:
            value = self.community.get_default_community()
        return value

    def status_icon_clicked(self):
        Change_Status_Window(self)

    def register_com_action_list(self, action_list):
        self.com_action_lists.append(action_list)

    def register_user_action_list(self, action_list):
        self.user_action_lists.append(action_list)

    def register_com_event(self, icon, name, callback):
        """ Register a new community event. Called when button is clicked. """
        event = (icon, name, callback)
        self.com_events.append(event)
        for l in self.com_action_lists:
            l.add_event(event)

    def register_user_event(self, icon, name, callback):
        """ Register a new user event. Called when button is clicked. """
        event = (icon, name, callback)
        self.user_events.append(event)
        for l in self.user_action_lists:
            l.add_event(event)

    def update_communities(self):
        myself = self.community.get_myself()
        communities = self.community.get_user_communities(myself)
        if self.community.personal_communities:
            communities += self.community.find_communities(peer=False)

        for row in self.itemlist:
            com = row[self.COL_COM]
            if com not in communities:
                self.itemlist.remove(row.iter)
            else:
                communities.remove(com)

        # add new communities to the end
        for com in communities:
            if not com.get('invisible'):
                self.itemlist.append([get_community_icon(com), com, com.get('name')])

    def create_user_page(self, user):
        page = User_Page(self.main_gui, self, user)
        page.show_all()
        self.user_pages[user] = page
        self.main_gui.add_page(page)
        return page

    def create_com_page(self, com):
        page = Community_Page(self, self.main_gui, com)
        page.show_all()
        self.com_pages[com] = page
        self.main_gui.add_page(page)
        return page

    def community_changes(self, com):
        for row in self.itemlist:
            if com == row[self.COL_COM]:
                row[self.COL_ICON] = get_community_icon(com)
                break
        page = self.com_pages.get(com)
        if page != None:
            page.update_community_page()

    def user_appears(self, user):
        for page in self.com_pages.values():
            page.user_changes(user)

        page = self.user_pages.get(user)
        if page != None:
            page.update_user_page()

    def user_changes(self, user, what):
        if user == self.community.get_myself():
            self.update_communities()

        for page in self.com_pages.values():
            page.user_changes(user)

        page = self.user_pages.get(user)
        if page != None:
            page.update_user_page()

    def user_disappears(self, user):
        self.user_appears(user)

    def show_com_page(self, com):
        page = self.com_pages.get(com)
        if page == None:
            page = self.create_com_page(com)
        self.main_gui.show_page(page)

    def show_user_page(self, user):
        page = self.user_pages.get(user)
        if page == None:
            page = self.create_user_page(user)
        self.main_gui.show_page(page)

    def manage_community_cb(self, com):
        Community_Management_GUI(com, self.main_gui, self)

    def initialize_menu(self):
        menu = gtk.Menu()
        item = gtk.MenuItem('Create community')
        item.connect('activate', self.create_community_clicked)
        menu.append(item)
        self.main_gui.add_menu('Community', menu)

    def create_community_clicked(self, menu, data=None):
        Community_Information_GUI('Create', self.main_gui)

class Community_Action_List(Action_List):
    def __init__(self, gui, get_selected_func):
        Action_List.__init__(self)
        self.get_selected = get_selected_func
        self.community_gui = gui
        for event in self.community_gui.com_events:
            self.add_event(event)
        self.community_gui.register_com_action_list(self)

    def add_event(self, event):
        (icon, name, callback) = event
        self.add_button(icon, name, self.action, callback)

    def action(self, callback):
        callback(self.get_selected())

class Community_Page(GUI_Page):
    COL_ICON = 0
    COL_USER = 1
    COL_TITLE = 2
    COL_STATUS = 3

    def __init__(self, community_gui, gui, com):
        GUI_Page.__init__(self, com.get('name'))

        self.notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)

        self.item_double_clicking = None
        self.community_gui = community_gui
        self.main_gui = gui
        self.com = com

        self.list_view = community_gui.list_view_setting.value

        self.profile_widgets = {}

        # model (icon, item, text)
        self.itemlist = gtk.ListStore(gtk.gdk.Pixbuf, gobject.TYPE_PYOBJECT, str, str)
        self.update_members()

        self.pic_dialog = Picture_Choose_Dialog(gui, self.got_picture)

        self.notebook = gtk.Notebook()
        self.notebook.set_show_tabs(True)
        self.notebook.set_show_border(False)
        self.initialize_members_page()
        self.initialize_profile_page()
        self.initialize_modify_page()
        self.pack_start(self.notebook)

    def initialize_members_page(self):
        hbox = gtk.HBox()

        if self.list_view:
            # Display as a list
            self.itemview = gtk.TreeView(self.itemlist)
            self.itemview.connect('row-activated', self.handle_item_clicked)
            self.itemview.set_headers_visible(False)

            cr_icon = gtk.CellRendererPixbuf()
            cr_name = gtk.CellRendererText()
            cr_status = gtk.CellRendererText()

            column = gtk.TreeViewColumn('')
            column.pack_start(cr_icon, False)
            column.pack_start(cr_name)
            column.add_attribute(cr_icon, 'pixbuf', self.COL_ICON)
            column.add_attribute(cr_name, 'markup', self.COL_TITLE)
            self.itemview.append_column(column)

            column = gtk.TreeViewColumn('Status')
            column.pack_start(cr_status)
            column.add_attribute(cr_status, 'text', self.COL_STATUS)
            column.set_expand(True)
            self.itemview.append_column(column)
        else:
            # Icon display
            self.itemview = gtk.IconView(self.itemlist)
            self.itemview.set_spacing(6)
            self.itemview.set_row_spacing(9)
            self.itemview.connect('item-activated', self.handle_item_clicked)
            self.itemview.connect('button-press-event', self.view_clicked, None)
            self.itemview.set_pixbuf_column(self.COL_ICON)
            self.itemview.set_markup_column(self.COL_TITLE)

        swindow = new_scrollarea()
        swindow.add_with_viewport(self.itemview)

        hbox.pack_start(swindow)

        self.action_list = User_Action_List(self.community_gui, self.get_selected)
        hbox.pack_start(self.action_list.get_widget(), False, True)

        self.notebook.append_page(hbox, gtk.Label('Members'))

    def back_action(self):
        self.community_gui.com_pages.pop(self.com)
        self.main_gui.remove_page(self)
        self.destroy()
        return True

    def get_community(self):
        return self.com

    def update_community_page(self):
        self.update_profile_entries()
        self.update_profile_widgets()

    def update_members(self):
        users = self.community.get_community_members(self.com)
        myself = self.community.get_myself()
        # myself is not in active users list, so add separately here
        if self.com.get('peer') == True and \
           self.com in self.community.get_user_communities(myself):
            users.append(myself)

        for row in self.itemlist:
            user = row[self.COL_USER]
            if user not in users:
                self.itemlist.remove(row.iter)
            else:
                users.remove(user)

        # add new users to the end
        for user in users:
            icon = self.get_user_icon(user)
            title = self.get_user_display_name(user)
            if user == myself:
                self.itemlist.prepend([icon, user, title, user.get('status')])
            else:
                self.itemlist.append([icon, user, title, user.get('status')])

    def get_user_icon(self, user):
        icon = get_user_profile_picture(user)
        if self.list_view:
            return icon.scale_simple(48, 48, gtk.gdk.INTERP_BILINEAR)
        return icon

    def user_changes(self, user):
        self.update_members()
        self.update_profile_widgets()
        for row in self.itemlist:
            if user == row[self.COL_USER]:
                row[self.COL_ICON] = self.get_user_icon(user)
                row[self.COL_TITLE] = self.get_user_display_name(user)
                row[self.COL_STATUS] = user.get('status')
                break

    def get_user_display_name(self, user):
        nick = pango_escape(user.get('nick'))
        if user == self.community.get_myself():
            nick = '<b>%s</b> (me)' % nick
        return nick

    def handle_item_clicked(self, view, path, view_column=None):
        row = self.itemlist[path]
        user = row[self.COL_USER]
        self.community_gui.show_user_page(user)

    def view_clicked(self, iconview, event, param):
        if event.type == gtk.gdk.BUTTON_PRESS and event.button == 1:
            coords = event.get_coords()
            if coords == ():
                return
            (x,y) = coords

            # simulate double click with a timeout variable
            if not self.item_double_clicking:
                self.set_item_double_clicking(True)
                timeout_id = gobject.timeout_add(500, self.set_item_double_clicking, False)
                return

            path = iconview.get_path_at_pos(int(x), int(y))
            if path != None:
                # is the item already selected
                selected = iconview.path_is_selected(path)
                if selected:
                    self.handle_item_clicked(iconview, path)

    def set_item_double_clicking(self, doubleclick):
        self.item_double_clicking = doubleclick
        return False # timeout shouldn't call this again

    def get_selected(self):
        if self.list_view:
            model, selected = self.itemview.get_selection().get_selected_rows()
        else:
            selected = self.itemview.get_selected_items()
        if len(selected) > 0:
            path = selected[0] # there should be 0 or 1 selected items
            row = self.itemlist[path]
            value = row[self.COL_USER]
        else:
            value = self.com
        return value

    def initialize_profile_page(self):
        profile_hbox = gtk.HBox()
        vbox = gtk.VBox()

        myself = self.community.get_myself()
        is_member = (self.com in self.community.get_user_communities(myself))

        picture_vbox = gtk.VBox()
        self.profile_image = gtk.Image()
        self.profile_image.set_size_request(MAX_FACE_DIMENSION+10, MAX_FACE_DIMENSION+10)
        if is_member:
            eventbox = gtk.EventBox()
            eventbox.connect("button-press-event", self.image_clicked)
            eventbox.add(self.profile_image)
            picture_vbox.pack_start(gtk.Label('Click picture to change'))
            picture_vbox.pack_start(eventbox, True, True)
        else:
            picture_vbox.pack_start(self.profile_image, True, True)

        picture_hbox = gtk.HBox()
        picture_hbox.pack_start(picture_vbox, False, True)
        self.status_label = gtk.Label()
        self.status_label.set_line_wrap(True)
        picture_hbox.pack_start(self.status_label)
        vbox.pack_start(picture_hbox)

        self.profile_info_label = gtk.Label()
        self.profile_info_label.set_alignment(0.1, 0.01) # 0.01 on purpose
        self.profile_info_label.set_line_wrap(True)
        vbox.pack_start(self.profile_info_label)

        profile_hbox.pack_start(vbox)

        self.com_action_list = Community_Action_List(self.community_gui,
            self.get_community)
        profile_hbox.pack_start(self.com_action_list.action_view)

        swindow = new_scrollarea()
        swindow.set_border_width(0)
        swindow.add_with_viewport(profile_hbox)

        self.update_profile_widgets()

        self.notebook.append_page(swindow, gtk.Label('Profile'))

    def initialize_modify_page(self):
        vbox = gtk.VBox()

        # List of modifiable fields
        profile_components = [('Location: ', 'location'),
                              ('WWW: ', 'www'),
                              ('Description: ', 'description'),
                             ]

        for header, key in profile_components:
            hbox = gtk.HBox()
            label = gtk.Label(header)
            label.set_size_request(130, -1)
            label.set_alignment(0, 0)

            value = self.com.get(key)
            if value == None:
                value = ''

            if key == 'description':
                # create description widget separately
                entry = gtk.TextView()
                entry.get_buffer().set_text(str(value))
                entry.set_property("wrap-mode", gtk.WRAP_CHAR)
                entry.set_size_request(-1, 100)
            else:
                entry = gtk.Entry()
                entry.set_text(str(value))

            entry.connect("focus-out-event", self.entry_focus_out, key)

            hbox.pack_start(label, False)
            hbox.pack_start(entry)

            self.profile_widgets[key] = entry
            vbox.pack_start(hbox, False)

        self.locked_checkbox = gtk.CheckButton('Do not allow changes to the community icon from other users')
        vbox.pack_start(self.locked_checkbox, False, False)
        self.locked_checkbox.set_active(self.com.get('iconlocked'))
        self.locked_checkbox.connect('toggled', self.set_locked)

        myself = self.community.get_myself()
        if self.com in self.community.get_user_communities(myself):
            self.notebook.append_page(vbox, gtk.Label('Modify'))

        self.update_profile_entries()

    def set_locked(self, widget):
        self.com.set('iconlocked', widget.get_active())

    def update_profile_entries(self):
        for key, entry in self.profile_widgets.items():
            value = self.com.get(key)
            if value == None:
                value = ''

            if key == 'description':
                entry.get_buffer().set_text(str(value))
            else:
                entry.set_text(str(value))

    def update_profile_widgets(self):
        image = get_community_icon(self.com)
        self.profile_image.set_from_pixbuf(image)
        n = len(self.community.get_community_members(self.com))
        myself = self.community.get_myself()
        if self.com in self.community.get_user_communities(myself):
            n += 1
        status = '%d member' % n
        if n != 1:
            status += 's'
        self.status_label.set_text(status)
        self.profile_info_label.set_markup(self.construct_profile_info_str())

    def image_clicked(self, widget, event):
        self.pic_dialog.set_picture(seek_community_icon_name(self.com))
        self.pic_dialog.show()

    def got_picture(self, fname):
        myself = self.community.get_myself()
        if self.com in self.community.get_user_communities(myself):
            self.community.set_community_icon(self.com, fname)
            # increase profile version to indicate new community profile
            self.community.get_myself().update_attributes([])

    def construct_profile_info_str(self):

        def heading(s):
            # Returns a heading string s formatted with pango markup and
            # a new-line
            return '<span color="slategray" weight="bold" size="large">%s</span>\n' % pango_escape(s)

        def field(s):
            value = self.com.get(s)
            if value != None:
                return '%s: %s\n' % (field_descriptions[s], pango_escape(str(value)))
            else:
                return ''

        def join_list(l):
            out = []
            for s in l:
                value = self.com.get(s)
                if value != None:
                    out.append(pango_escape(str(value)))
            if len(out) > 0:
                return ', '.join(out) + '\n'
            else:
                return ''

        s = heading(self.com.get('name'))
        s += field('location')
        s += field('www')
        s += field('description')

        if get_debug_mode():
            s += heading('Debug information')
            s += field('v')
            s += field('iconversion')
            s += field('myiconversion')

        return s

    def entry_focus_out(self, entry, event, key):
        if key == 'description':
            buf = entry.get_buffer()
            value = buf.get_text(buf.get_start_iter(), buf.get_end_iter())
        else:
            value = entry.get_text()
        if value == '':
            value = None
        if value != self.com.get(key):
            if self.com.set(key, value):
                # increase profile version to indicate new community profile
                self.community.get_myself().update_attributes([])
            else:
                # re-insert old value if set fails
                value = self.com.get(key)
                if value == None:
                    value = ''
                entry.set_text(str(value))

class Join_Community_Dialog(Community_List_Dialog):
    def __init__(self, gui):
        Community_List_Dialog.__init__(self, gui, 'Join Community', actiontext='Join')

        myself = self.community.get_myself()
        communities = self.community.find_communities(peer=True)
        my_communities = self.community.get_user_communities(myself)
        for com in communities:
            if not com in my_communities:
                num_members = len(self.community.get_community_members(com))
                if num_members > 0:
                    self.add_community(com)

    def community_selected(self, com):
        self.community.join_community(com)

class Community_Management_GUI:
    """ Shows a dialog with community management options depended on
    the target community's type."""
    
    def __init__(self, com, gui, community_gui):
        self.main_gui = gui
        self.community_gui = community_gui
        self.notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)

        self.create_icon = join(get_dir(ICON_DIR), "128px-create_community_icon.png")
        directory = get_dir(ICON_DIR)
        self.join_icon = join(directory, "128px-ok_icon.png")
        self.leave_icon = join(directory, "128px-no_icon.png")
        self.delete_icon = self.leave_icon
        self.cancel_icon = join(directory, "128px-cancel_icon.png")
                                
        self.CREATE_EVENT = 1
        self.JOIN_EVENT = 2
        self.LEAVE_EVENT = 3
        self.DELETE_EVENT = 4
        self.CANCEL_EVENT = 6
        
        self.com = com
        self.main_window = gui.get_main_window()

        self.dialog = gtk.Dialog('Community Management', self.main_window)
        self.dialog.set_has_separator(False)
        self.dialog.set_default_size(350, -1)

        self.initialize_widgets()
        self.dialog.connect("response", self.response_handler)
        self.dialog.set_modal(True)
        self.dialog.show_all()

    def response_handler(self, widget, event, cmd_id=None):
        self.dialog.set_modal(False)
        myself = self.community.get_myself()

        if cmd_id == self.CREATE_EVENT:
            Community_Information_GUI('Create', self.main_gui)

        elif cmd_id == self.JOIN_EVENT:
            Join_Community_Dialog(self.main_gui)

        elif cmd_id == self.DELETE_EVENT:
            self.community.delete_personal_community(self.com)
            self.notification.notify('Deleted community %s' %(self.com.get('name')))

        elif cmd_id == self.LEAVE_EVENT:
            self.community.leave_community(self.com)

        self.dialog.destroy()
        return True
    
    def initialize_widgets(self):
        self.hbox = gtk.HBox()
        self.hbox.set_spacing(15)
        self.hbox.set_property("border-width", 0)

        create_ebox = gtk.EventBox()
        join_ebox = gtk.EventBox()
        leave_ebox = gtk.EventBox()
        delete_ebox = gtk.EventBox()
        cancel_ebox = gtk.EventBox()

        create_image = gtk.Image()
        create_image.set_from_file(self.create_icon)
        join_image = gtk.Image()
        join_image.set_from_file(self.join_icon)
        leave_image = gtk.Image()
        leave_image.set_from_file(self.leave_icon)
        delete_image = gtk.Image()
        delete_image.set_from_file(self.delete_icon)
        cancel_image = gtk.Image()
        cancel_image.set_from_file(self.cancel_icon)

        create_ebox.add(create_image)
        join_ebox.add(join_image)
        leave_ebox.add(leave_image)
        delete_ebox.add(delete_image)
        cancel_ebox.add(cancel_image)

        create_ebox.connect("button-press-event", self.response_handler, \
                            self.CREATE_EVENT)
        join_ebox.connect("button-press-event", self.response_handler, \
                          self.JOIN_EVENT)
        leave_ebox.connect("button-press-event", self.response_handler, \
                           self.LEAVE_EVENT)
        delete_ebox.connect("button-press-event", self.response_handler, \
                            self.DELETE_EVENT)
        cancel_ebox.connect("button-press-event", self.response_handler, \
                            self.CANCEL_EVENT)

        default = self.community.get_default_community()
        friend = self.community.get_friend_community()

        vbox1 = gtk.VBox()
        vbox1.pack_start(create_ebox, True, True)
        vbox1.pack_start(gtk.Label('Create'), False, False)
        self.hbox.pack_start(vbox1, True, True)

        # Join a peer community
        vbox2 = gtk.VBox()
        vbox2.pack_start(join_ebox, True, True)
        vbox2.pack_start(gtk.Label('Join'), False, False)
        self.hbox.pack_start(vbox2, True, True)

        # Leave a peer community
        if self.com.get('peer') == True and self.com != default:
            vbox4 = gtk.VBox()
            vbox4.pack_start(leave_ebox, True, True)
            vbox4.pack_start(gtk.Label('Leave'), False, False)
            self.hbox.pack_start(vbox4, True, True)

        # Delete a personal community
        if self.com != friend and self.com.get('peer') == False:
            vbox5 = gtk.VBox()
            vbox5.pack_start(delete_ebox, True, True)
            vbox5.pack_start(gtk.Label('Delete'), False, False)
            self.hbox.pack_start(vbox5, True, True)
        
        vbox6 = gtk.VBox()
        vbox6.pack_start(cancel_ebox, True, True)
        vbox6.pack_start(gtk.Label('Cancel'), False, False)
        self.hbox.pack_start(vbox6, True, True)
        
        self.dialog.vbox.pack_start(self.hbox, True, True, 0)
        self.dialog.action_area.set_size_request(0,0)
        self.dialog.vbox.set_spacing(0)
        self.dialog.vbox.show_all()

class Community_Information_GUI:
    """The Class can be used to create new peer/personal communities."""
    
    def __init__(self, title, gui):
        self.main_gui = gui
        self.personal_community = False

        self.icon_fname = None
        self.icon_changed = False
        self.notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)

        self.main_window = gui.get_main_window()

        new_title = title + ' Community'
        self.dialog = gtk.Dialog(new_title, self.main_window, \
                                 gtk.DIALOG_DESTROY_WITH_PARENT | gtk.DIALOG_MODAL, \
                                 (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, \
                                  title, gtk.RESPONSE_OK))
        # this should be better for toplevel windows than set_size_request()
        self.dialog.set_default_size(400, 300)

        self.initialize_widgets()
        self.dialog.connect("response", self.response_handler)
        self.dialog.show_all()

        self.pic_dialog = Picture_Choose_Dialog(self.main_gui, self.got_picture)

    def response_handler(self, widget, event):
        if event == gtk.RESPONSE_OK:
            self.community_name = self.name_entry.get_text()
            if not valid_community(self.community_name):
                self.notification.ok_dialog('Error', 'Invalid community name.',
                    parent=self.dialog, modal=True)
                return True

            self.desc = self.description_tbuffer.get_text(self.description_tbuffer.get_start_iter(), self.description_tbuffer.get_end_iter())
            if self.desc == "<<Insert description>>":
                self.desc = None
                
            self.save_community_information(self.personal_community == False)

        self.pic_dialog.close()
        self.dialog.destroy()
        return True

    def save_community_information(self, peer=True):
        if peer:
            com = self.community.create_community(self.community_name, desc=self.desc)
            self.community.join_community(com)

            if self.icon_changed and not self.community.set_community_icon(com, self.icon_fname):
                self.notification.notify('Could not set community icon', True)
        else:
            # personal, public
            com = self.community.create_community(self.community_name, False, True, desc=self.desc)

            if self.icon_changed and not self.community.set_community_icon(com, self.icon_fname):
                self.notification.notify('Could not set community icon', True)
                
    def initialize_widgets(self):
        fwindow = new_scrollarea()
        viewport = gtk.Viewport()

        self.widgets_to_hide = []
        self.main_vbox = gtk.VBox()
        self.main_vbox.set_size_request(-1, 500)
        self.image_hbox = gtk.HBox()
        self.main_vbox.pack_start(self.image_hbox, False, False)

        # Community name, personal cbox, area size and image
        self.name_vbox = gtk.VBox()
        hbox = gtk.HBox()
        self.name_label = gtk.Label('Community\'s name:')
        hbox.pack_start(self.name_label, False, True)
        self.name_vbox.pack_start(hbox, False, True)
        self.name_entry = gtk.Entry()
        self.name_entry.set_size_request(-1, 32)
        self.name_vbox.pack_start(self.name_entry, False, True)

        hbox = gtk.HBox()
        self.personal_label = gtk.Label('Personal Community:')
        hbox.pack_start(self.personal_label, False, True)
        if self.community.personal_communities:
            self.name_vbox.pack_start(hbox, False, True)
        self.personal_cbutton = gtk.CheckButton()
        self.personal_cbutton.set_active(False)
        self.personal_cbutton.set_size_request(-1, 32)
        self.personal_cbutton.connect("clicked", self.checkbutton_clicked)
        hbox = gtk.HBox()
        hbox.pack_start(self.personal_cbutton, True, True)
        if self.community.personal_communities:
            self.name_vbox.pack_start(hbox, False, True)

        self.image_hbox.pack_start(self.name_vbox, False, True)
        self.image_eb = gtk.EventBox()
        self.image_eb.connect("button-press-event", self.image_clicked)
        self.image = gtk.Image()
        self.image.set_size_request(MAX_FACE_DIMENSION+10, MAX_FACE_DIMENSION+10)
        self.image.set_from_file(get_path(DEFAULT_COMMUNITY_ICON))
        self.image_eb.add(self.image)
        vbox = gtk.VBox()
        vbox.pack_start(self.image_eb, True, True)
        vbox.pack_start(gtk.Label('Click community\nicon to change it'), True, False)
        self.image_hbox.pack_end(vbox, False, False)
        
        hbox = gtk.HBox()
        desc_label = gtk.Label('Description: ')
        desc_label.set_size_request(-1, 32)
        hbox.pack_start(desc_label, False, True)
        self.main_vbox.pack_start(hbox, False, True)
        self.description_tview = gtk.TextView()
        self.description_tview.set_property("wrap-mode", gtk.WRAP_CHAR)
        self.description_tbuffer = gtk.TextBuffer()
        self.description_tbuffer.set_text("<<Insert description>>")
        self.description_tview.set_buffer(self.description_tbuffer)
        self.description_tview.set_size_request(300, 100)
        
        self.main_vbox.pack_start(self.description_tview, False, True)
        self.main_vbox.show_all()
        viewport.add(self.main_vbox)
        fwindow.add(viewport)
        self.dialog.vbox.pack_start(fwindow)

    def initialize_date_and_time_widgets(self):
        # community activation
        hbox = gtk.HBox()
        hbox.pack_start(gtk.Label('Activation Date & Time:'), False, True)
        self.widgets_to_hide.append(hbox)
        self.main_vbox.pack_start(hbox, False, True)

        hbox = gtk.HBox()
        self.start_date_entry = gtk.Entry()
        self.start_date_entry.set_size_request(-1, 32)
        self.start_date_button = gtk.Button("Date")
        self.start_date_button.set_size_request(80, -1)
        self.start_date_button.connect("clicked", self.sdate_clicked)
        hbox.pack_start(self.start_date_entry, False, True)
        hbox.pack_start(self.start_date_button, False, True)
        self.widgets_to_hide.append(hbox)
        self.main_vbox.pack_start(hbox, False, True)
        self.start_time_entry = gtk.Entry()
        self.start_time_entry.set_size_request(-1, 32)
        self.start_time_button = gtk.Button("Time")
        self.start_time_button.set_size_request(80, -1)
        self.start_time_button.connect("clicked", self.stime_clicked)
        hbox = gtk.HBox()
        hbox.pack_start(self.start_time_entry, False, True)
        hbox.pack_start(self.start_time_button, False, True)
        self.widgets_to_hide.append(hbox)
        self.main_vbox.pack_start(hbox, False, True)

        # community deactivation
        hbox = gtk.HBox()
        hbox.pack_start(gtk.Label('Deactivation Date & Time:'), False, True)
        self.widgets_to_hide.append(hbox)
        self.main_vbox.pack_start(hbox, False, True)

        hbox = gtk.HBox()
        self.end_date_entry = gtk.Entry()
        self.end_date_entry.set_size_request(-1, 32)
        self.end_date_button = gtk.Button("Date")
        self.end_date_button.set_size_request(80, -1)
        self.end_date_button.connect("clicked", self.sdate_clicked, False)
        hbox.pack_start(self.end_date_entry, False, True)
        hbox.pack_start(self.end_date_button, False, True)
        self.widgets_to_hide.append(hbox)
        self.main_vbox.pack_start(hbox, False, True)
        self.end_time_entry = gtk.Entry()
        self.end_time_entry.set_size_request(-1, 32)
        self.end_time_button = gtk.Button("Time")
        self.end_time_button.set_size_request(80, -1)
        self.end_time_button.connect("clicked", self.stime_clicked, False)
        hbox = gtk.HBox()
        hbox.pack_start(self.end_time_entry, False, True)
        hbox.pack_start(self.end_time_button, False, True)
        self.widgets_to_hide.append(hbox)
        self.main_vbox.pack_start(hbox, False, True)

    def checkbutton_clicked(self, widget):
        self.personal_community = self.personal_cbutton.get_active()

        if self.personal_community:
            for widget in self.widgets_to_hide:
                widget.hide_all()
        else:
            for widget in self.widgets_to_hide:
                widget.show_all()

    def image_clicked(self, widget, event=None):
        self.pic_dialog.set_picture(self.icon_fname)
        self.pic_dialog.show()

    def got_picture(self, fname):
        self.icon_fname = fname
        self.icon_changed = True
        if fname != None:
            self.image.set_from_file(fname)
        else:
            self.image.set_from_pixbuf(get_default_community_icon(self.com))

    def sdate_clicked(self, widget, start = True):
        fields = time.localtime()
        dialog = hildon.CalendarPopup(self.main_window, fields[0], fields[2], \
                                      fields[3])
        dialog.run()
        date = dialog.get_date()
        dialog.destroy()
        (year, month, day) = date
        if start:
            self.start_date_entry.set_text('%.4d-%.2d-%.2d' %(year, month, day))
        else:
            self.end_date_entry.set_text('%.4d-%.2d-%.2d' %(year, month, day))

    def stime_clicked(self, widget, start = True):
        time_picker = hildon.TimePicker(self.main_window)
        time_picker.run()
        selected_time = time_picker.get_time()
        time_picker.destroy()
        (hours, minutes) = selected_time

        str_hours = '%.2d' %(hours)
        str_mins = '%.2d' %(minutes)

        if start:
            self.start_time_entry.set_text('%s:%s' %(str_hours, str_mins))
        else:
            self.end_time_entry.set_text('%s:%s' %(str_hours, str_mins))

class Edit_Community_Meta_Dialog(Community_Information_GUI):
    def __init__(self, com, gui):
        self.com = com

        Community_Information_GUI.__init__(self, 'Modify', gui)
        self.load_community_information()

    def load_community_information(self):
        self.cname = self.com.get('name')
        self.name_label.hide()
        self.name_entry.set_text(self.cname)
        self.name_entry.hide()
        self.peer = self.com.get('peer')
        
        if self.peer:
            ctype = 'Peer'
        else:
            ctype = 'Personal'
            self.personal_cbutton.set_active(True)
            self.checkbutton_clicked(None)

        # Hide checkbutton & label
        self.personal_label.hide()
        self.personal_cbutton.hide()
        
        self.dialog.set_title('Modify %s [%s]' %(self.cname, ctype))

        # number of hops is not currently used
        temp = self.com.get('description')
        if temp != None:
            self.description_tbuffer.set_text(temp)

        self.icon_fname = seek_community_icon_name(self.com)
        self.image.set_from_pixbuf(get_community_icon(self.com))

    def save_community_information(self, peer=True):
        """ Overrides base class function. """

        myself = self.community.get_myself()
        self.com.set('creator', myself.get('nick'))
        self.com.set('creatoruid', myself.get('uid'))
        self.com.set('description', self.desc)

        if self.icon_changed and not self.community.set_community_icon(self.com, self.icon_fname):
            self.notification.notify('Could not set community icon', True)

        self.community.save_communities([self.com])

        # increase profile version to indicate new community profile
        self.community.get_myself().update_attributes([])

class Change_Status_Window:
    def __init__(self, gui):
        self.community_gui = gui
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        self.notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)

        self.window = gtk.Dialog('Change Status',
                                buttons = (gtk.STOCK_OK, gtk.RESPONSE_OK,
                                gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL))
        self.window.set_modal(True)
        self.window.set_border_width(5)
        self.window.vbox.set_spacing(5)
        self.window.set_has_separator(False)

        self.status_buttons = {}
        myself = self.community.get_myself()
        status_group = gtk.RadioButton()

        def button_row(statuslist):
            icons_hbox = gtk.HBox(True, 10)
            for status in statuslist:
                radiobutton = gtk.RadioButton(status_group)
                self.status_buttons[status] = radiobutton
                vbox = gtk.VBox()

                image = gtk.image_new_from_pixbuf(get_status_icon(status, STATUSBAR_ICON_SIZE))
                vbox.pack_start(image, False, True)
                vbox.pack_start(gtk.Label(status.title()), False, True)
                radiobutton.set_mode(False)
                if status == myself.get('status_icon'):
                    radiobutton.set_active(True)
                radiobutton.add(vbox)
                icons_hbox.pack_start(radiobutton, False, True)
            return icons_hbox

        self.window.vbox.pack_start(button_row(USER_STATUS_LIST[0:3]), False, False)
        self.window.vbox.pack_start(button_row(USER_STATUS_LIST[3:]), False, False)

        self.window.vbox.pack_start(gtk.Label('What is on your mind?'), False, True)
        self.status_entry = gtk.Entry()
        status = myself.get('status')
        if status != None:
            self.status_entry.set_text(status)
        self.window.vbox.pack_start(self.status_entry, True, True)

        self.window.connect("response", self.response_handler)
        self.window.show_all()

    def response_handler(self, dialog, response_id, data = None):
        if response_id == gtk.RESPONSE_OK:
            myself = self.community.get_myself()

            status_icon = None
            for (status, radiobutton) in self.status_buttons.items():
                if radiobutton.get_active():
                    status_icon = status
                    break
            if status_icon == USER_STATUS_LIST[0]:
                status_icon = None
            myself.set('status_icon', status_icon)

            status = self.status_entry.get_text()
            if len(status) == 0:
                status = None
            myself.set('status', status)

            status_icon_pixbuf = get_status_icon(status_icon, STATUSBAR_ICON_SIZE)
            icon = self.community_gui.status_icon.get_children()[0]
            icon.set_from_pixbuf(status_icon_pixbuf)

            self.community.announce_user_change(myself, allowme=True)
            self.community.show_status_change(myself)

        self.window.destroy()

def init_ui(main_gui):
    Community_GUI(main_gui)
