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
import re
import gtk
import pango
from os.path import join
from time import time

from guihandler import STATUSBAR_ICON_SIZE
from communitymeta import Community
from gui_user import get_user_profile_picture, get_community_icon
from guiutils import new_scrollarea, new_textview, GUI_Page, new_entry, \
    Action_List, pango_escape
from plugins import get_plugin_by_type
from pathname import get_dir, ICON_DIR
from support import warning
from proximateprotocol import PLUGIN_TYPE_COMMUNITY, PLUGIN_TYPE_NOTIFICATION, PLUGIN_TYPE_MESSAGING, \
    PLUGIN_TYPE_MESSAGE_BOARD
from utils import iso_date_time
from openfile import open_url
from watches_gui import Watches_GUI

community = None
msgboard = None
chat = None

def msgtime(meta):
    return iso_date_time(meta.get('timestart'))

class Messageboard_GUI(GUI_Page):

    MSGBOARD_ICON = '64px-msgboard_icon.png'
    MESSAGE_ICON = '64px-messaging_status_icon.png'
    REFRESH_ICON = '64px-refresh_icon.png'
    SEARCH_ICON = '64px-search_icon.png'
    NEW_MESSAGE_ICON = '64px-msgboard_icon.png'

    def __init__(self, gui):
        global community, msgboard, chat

        GUI_Page.__init__(self, 'Messageboard')
        community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        chat = get_plugin_by_type(PLUGIN_TYPE_MESSAGING)
        msgboard = get_plugin_by_type(PLUGIN_TYPE_MESSAGE_BOARD)

        self.notify = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION).notify

        self.main_gui = gui

        # Store Message_Page instances, key = sharemeta of the message
        self.message_pages = {}

        messageboard_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), self.MSGBOARD_ICON))

        community.community_gui.register_user_event(messageboard_icon, 'Msg board', self.start_messageboard_cb)
        community.community_gui.register_com_event(messageboard_icon, 'Msg board', self.start_messageboard_cb)

        self.message_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), self.MESSAGE_ICON))

        self.in_search_mode = False
        self.store = None
        self.search_store = None
        self.target = None

        # create widgets here
        self.create_action_list()
        self.message_list, self.message_view = self.create_message_list()

        self.search_hbox = gtk.HBox()
        self.search_entry = new_entry('Enter search keywords')
        self.search_entry.connect('activate', self.search_activate_cb)
        self.search_close = gtk.Button(stock=gtk.STOCK_CLOSE)
        self.search_close.connect('clicked', self.search_close_cb)
        self.search_now = gtk.Button(stock=gtk.STOCK_FIND)
        self.search_now.connect('clicked', self.search_now_cb)
        self.search_hbox.pack_start(self.search_entry, True, True)
        self.search_hbox.pack_start(self.search_close, False, True)
        self.search_hbox.pack_start(self.search_now, False, True)

        self.vbox = gtk.VBox()
        self.vbox.pack_start(self.message_list, True, True)
        self.vbox.pack_start(self.search_hbox, False, True)

        self.pack_start(self.vbox, True, True)
        self.pack_start(self.actions.get_widget(), False, True)

        self.show_all()
        self.search_hbox.hide()
        gui.add_page(self)

        gui.add_key_binding(gtk.gdk.CONTROL_MASK, gtk.keysyms.m, self.key_pressed_ctrl_m)

        msgboard.register_ui(self)

        self.watch_dialog = Watches_GUI(self.main_gui, msgboard.get_state, msgboard.modify_state)

    def append_messages_to_store(self, store, metas):
        # Display hot messages first
        hot = []
        normal = []
        for meta in metas:
            if msgboard.is_hot(meta):
                hot.append((True, meta))
            else:
                normal.append((False, meta))

        for l in hot, normal:
            for (ishot, meta) in l:
                user = None
                uid = meta.get('src')
                if uid != None:
                    user = community.get_user(uid)
                if user == community.get_myself():
                    sender = 'Myself'
                elif user != None:
                    sender = pango_escape(user.tag())
                else:
                    sender = pango_escape(meta.get('from'))
                timestamp = msgtime(meta)
                subject = pango_escape(meta.get('subject'))
                if ishot:
                    line = '%s <span foreground="gray"><small>%s</small></span>\n<span foreground="red">[HOT] </span><b>%s</b>' % (sender, timestamp, subject)
                else:
                    line = '%s <span foreground="gray"><small>%s</small></span>\n<b>%s</b>' % (sender, timestamp, subject)
                icon = self.message_icon
                if user != None:
                    icon = get_user_profile_picture(user).scale_simple(64, 64, gtk.gdk.INTERP_BILINEAR)
                store.append([icon, line, meta])

    def key_pressed_ctrl_m(self, target, ctx):
        self.start_messageboard_cb(target)

    def create_action_list(self):
        new_message_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), self.NEW_MESSAGE_ICON))
        refresh_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), self.REFRESH_ICON))
        search_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), self.SEARCH_ICON))

        action_buttons = [(new_message_icon, 'Compose', self.create_new_cb),
                          (refresh_icon, 'Refresh / All\nMessages', self.refresh_cb),
                          (new_message_icon, 'My\nMessages', self.my_messages_cb),
                          (search_icon, 'Search', self.search_cb),
                          (search_icon, 'Watches', self.watches_cb),
                         ]

        self.actions = Action_List()

        for action in action_buttons:
            (icon, text, cb) = action
            self.actions.add_button(icon, text, cb)

    def watches_cb(self, widget):
        self.watch_dialog.show()

    def create_message_list(self):
        message_list = new_scrollarea()
        message_view = gtk.TreeView()
        message_view.set_headers_visible(False)

        cr1 = gtk.CellRendererPixbuf()
        cr2 = gtk.CellRendererText()

        col1 = gtk.TreeViewColumn('Message')
        col1.pack_start(cr1, False)        
        col1.pack_start(cr2, True)

        message_view.append_column(col1)
        col1.add_attribute(cr1, 'pixbuf', 0)
        col1.add_attribute(cr2, 'markup', 1)

        message_view.connect('row-activated', self.row_activated_cb)

        message_list.add(message_view)

        return message_list, message_view

    def create_new_cb(self, widget):
        # HACK: first try Hildon StackableWindow-style
        try:
            composer = Message_Composer(self)
        except:
            composer = Message_Composer(self.main_gui.get_main_window())
        composer.show_all()
        response = composer.run()
        
        if response == 1:
            sender = community.get_myself().tag()            
            subject = composer.get_subject()
            text = composer.get_text()
            cname = None
            if self.target != None:
                cname = self.target.get('name')
            self.publish_message(sender, subject, text, cname)

        composer.destroy()

    def refresh_cb(self, widget, showmine=False):
        if self.in_search_mode:
            self.search_close_cb(None)
        msgboard.query_messages(showmine=showmine, target=self.target)

    def my_messages_cb(self, widget):
        self.refresh_cb(widget, showmine=True)

    def search_cb(self, widget):
        self.in_search_mode = True
        self.search_hbox.show()
        self.search_entry.grab_focus()
        if self.search_store:
            self.message_view.set_model(self.search_store)

    def search_close_cb(self, widget):
        self.in_search_mode = False
        self.search_hbox.hide()
        if self.store:
            self.message_view.set_model(self.store)

    def search_now_cb(self, widget):
        self.search_activate_cb(self.search_entry)

    def search_activate_cb(self, entry):
        self.search_store = gtk.ListStore(gtk.gdk.Pixbuf, str, object)
        self.message_view.set_model(self.search_store)
        text = entry.get_text().strip()
        keywords = text.split(',')
        criteria = None
        if self.target != None:
            criteria = {'community': self.target.get('name')}
        msgboard.search(self.got_query_results, criteria=criteria, keywords=keywords)
        if len(text) > 0:
            msg = 'Searching for %s' % text
        else:
            msg = 'Searching for all messages'
        self.notify(msg, delay=500)

    def got_query_results(self, user, metas, ctx):
        self.append_messages_to_store(self.search_store, metas)

    def row_activated_cb(self, treeview, path, view_column):
        store = treeview.get_model()
        row_iter = store.get_iter(path)
        meta = store.get(row_iter, 2)[0]
        self.view_message(meta)

    def view_message(self, msg):
        page = self.message_pages.get(msg)
        if page == None:
            page = Message_Page(self, msg)
            self.message_pages[msg] = page
        self.main_gui.show_page(page)

    def start_messageboard_cb(self, target):
        if not isinstance(target, Community):
            target = None
        if target == community.get_default_community():
            target = None
        self.target = target
        msgboard.query_messages(target=self.target)
        subtitle = None
        if self.target != None:
            subtitle = target.get('name')
        self.set_page_title(subtitle, sub=True)
        self.main_gui.show_page(self)

    def update_message_list(self, metas):
        self.store = gtk.ListStore(gtk.gdk.Pixbuf, str, object)

        self.append_messages_to_store(self.store, metas)

        if not self.in_search_mode:
            self.message_view.set_model(self.store)

    def message_deleted_cb(self, meta):
        store = self.store
        if store == None:
            return

        for row in store:
            if row[2] == meta:
                store.remove(row.iter)

    def publish_message(self, sender, subject, msg, cname=None):
        d = {'from': sender,
             'subject': subject,
             'msg': msg,
             'timestart': int(time()),
            }
        if cname != None:
            d['community'] = cname
        msgboard.publish(d)
        self.refresh_cb(None)

class Message_Composer(gtk.Dialog):

    SEARCH_ICON = '64px-search_content_icon.png'
    NEW_MESSAGE_ICON = '64px-add_content_icon.png'
    
    def __init__(self, parent, subject=None, text=None):
        gtk.Dialog.__init__(self, 'Message Composer', parent,
                            gtk.DIALOG_DESTROY_WITH_PARENT | gtk.DIALOG_MODAL,
                            (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL))

        self.add_button('Publish', 1)

        self.top_hbox = gtk.HBox()

        self.subject_label = gtk.Label()
        self.subject_label.set_use_markup(True)
        self.subject_label.set_markup('Subject:')
        self.subject_entry = new_entry()
        if subject != None:
            self.subject_entry.set_text(subject)

        self.top_hbox.pack_start(self.subject_label, False, False, 5)
        self.top_hbox.pack_start(self.subject_entry, True, True, 5)

        self.messagebuffer = gtk.TextBuffer()
        if text != None:
            self.messagebuffer.set_text(text)

        text_scrollarea = new_scrollarea()
        self.editor = new_textview()        
        self.editor.set_buffer(self.messagebuffer)
        self.editor.set_wrap_mode(gtk.WRAP_WORD)
        self.editor.set_editable(True)
        self.editor.set_cursor_visible(True)
        text_scrollarea.add(self.editor)
        text_scrollarea.set_size_request(-1, 300)

        self.vbox.pack_start(self.top_hbox, False, False)
        self.vbox.pack_start(text_scrollarea, True, True)

        self.vbox.show_all()

    def get_subject(self):
        return self.subject_entry.get_text()

    def get_text(self):
        start = self.messagebuffer.get_start_iter()
        end = self.messagebuffer.get_end_iter()
        return self.messagebuffer.get_text(start, end)

class Message_Page(GUI_Page):
    def __init__(self, gui, msg):

        self.gui = gui
        self.main_gui = gui.main_gui
        self.msg = msg

        self.user = None
        uid = msg.get('src')
        if uid != None:
            self.user = community.get_user(uid)

        if self.user == community.get_myself():
            sender = 'Myself'
        elif self.user != None:
            sender = self.user.tag()
        else:
            sender = msg.get('from')

        subject = msg.get('subject')
        title = 'Message from %s: %s' % (sender, subject)
        GUI_Page.__init__(self, title)

        self.vbox = gtk.VBox()

        self.top_hbox = gtk.HBox(False, 10)

        if self.user != None:
            self.profile_image = gtk.Image()
            self.profile_image.set_size_request(64+5, 64+5)
            icon = get_user_profile_picture(self.user).scale_simple(64, 64, gtk.gdk.INTERP_BILINEAR)
            self.profile_image.set_from_pixbuf(icon)
            eventbox = gtk.EventBox()
            eventbox.connect("button-press-event", self.image_clicked)
            eventbox.add(self.profile_image)
            self.top_hbox.pack_start(eventbox, False, True)

        self.info_widgets = {}

        info_vbox = gtk.VBox()

        label = gtk.Label()
        label.set_markup('<b>From:</b>')
        label.set_size_request(100, -1)
        label.set_alignment(1, 0)
        widget = gtk.Label()
        widget.set_markup('<span color="#ff0000"><u>%s</u></span>' % pango_escape(sender))
        widget.set_alignment(0, 0)
        eventbox = gtk.EventBox()
        eventbox.connect("button-press-event", self.image_clicked)
        eventbox.add(widget)

        hbox = gtk.HBox(False, 5)
        hbox.pack_start(label, False, False)
        hbox.pack_start(eventbox, True, True)
        info_vbox.pack_start(hbox, False, True)

        for name in ('subject', 'date'):
            label = gtk.Label()
            label.set_markup('<b>%s:</b>' % name.title())
            label.set_size_request(100, -1)
            label.set_alignment(1, 0)
            if name == 'date':
                value = msgtime(msg)
            else:
                value = msg.get(name)
            widget = gtk.Label(value)
            widget.set_alignment(0, 0)

            hbox = gtk.HBox(False, 5)
            hbox.pack_start(label, False, False)
            hbox.pack_start(widget, True, True)
            info_vbox.pack_start(hbox, False, False)

            self.info_widgets[name] = widget

        self.edit_button = gtk.Button(label='Edit', stock=gtk.STOCK_EDIT)
        self.edit_button.connect('clicked', self.edit_cb)

        self.delete_button = gtk.Button(label='Delete', stock=gtk.STOCK_DELETE)
        self.delete_button.connect('clicked', self.delete_cb)

        self.top_hbox.pack_start(info_vbox, True, True)
        self.top_hbox.pack_start(self.edit_button, False, False)
        self.top_hbox.pack_start(self.delete_button, False, False)

        # Message textview
        message_scrollarea = new_scrollarea()
        self.messagebuffer = gtk.TextBuffer()
        self.messageview = new_textview()
        self.messageview.set_buffer(self.messagebuffer)
        self.messageview.set_wrap_mode(gtk.WRAP_WORD)
        self.messageview.set_editable(False)
        self.messageview.set_cursor_visible(False)
        message_scrollarea.add(self.messageview)

        self.vbox.pack_start(self.top_hbox, expand=False, fill=True)
        self.vbox.pack_start(message_scrollarea, expand=True, fill=True)
        self.pack_start(self.vbox)

        self.urltag = self.messagebuffer.create_tag()
        self.urltag.set_property('foreground', '#0000ff')
        self.urltag.set_property('underline', pango.UNDERLINE_SINGLE)
        self.urltag.connect('event', self.urltag_event_cb)

        self.load_message()

        self.show_all()
        self.main_gui.add_page(self)

    def back_action(self):
        self.gui.message_pages.pop(self.msg)
        self.main_gui.remove_page(self)
        return True

    def image_clicked(self, widget, event):
        community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        community.community_gui.show_user_page(self.user)

    def edit_cb(self, widget):
        subject = self.msg.get('subject')
        text = self.messagebuffer.get_text(self.messagebuffer.get_start_iter(),
                                           self.messagebuffer.get_end_iter())
        composer = Message_Composer(self.main_gui.get_main_window(), subject, text)
        response = composer.run()

        if response == 1:
            msgboard.delete(self.msg)
            sender = community.get_myself().tag()
            subject = composer.get_subject()
            text = composer.get_text()
            self.gui.publish_message(sender, subject, text, self.msg.get('community'))
            self.main_gui.remove_page(self)

        composer.destroy()

    def delete_cb(self, widget):
        msgboard.delete(self.msg)
        self.main_gui.remove_page(self)

    def chat_cb(self, widget):
        uid = self.msg.get('src')
        user = community.get_user(uid)
        if user == community.get_myself():
            warning('Trying to chat with yourself')
            return None
        chat.messaging_gui.start_messaging(user, False)

    def urltag_event_cb(self, tag, textview, event, iter):
        if event.type == gtk.gdk.BUTTON_PRESS:
            begin_iter = iter.copy()
            end_iter = iter.copy()
            while not begin_iter.begins_tag():
                begin_iter.backward_char()

            while not end_iter.ends_tag():
                end_iter.forward_char()

            buffer = iter.get_buffer()
            tagtext = buffer.get_text(begin_iter, end_iter)
            open_url(tagtext)

    def set_text(self, text):
        r = re.compile('(https?://[^ ]+)')

        pieces = r.split(text)

        for piece in pieces:
            if r.match(piece):
                self.messagebuffer.insert_with_tags(self.messagebuffer.get_end_iter(), piece, self.urltag)
            else:
                self.messagebuffer.insert(self.messagebuffer.get_end_iter(), piece)

    def load_message(self):
        self.set_text(self.msg.get('msg'))
        self.delete_button.set_sensitive(self.msg.get_priv('shared'))
        self.edit_button.set_sensitive(self.msg.get_priv('mine'))

def init_ui(main_gui):
    Messageboard_GUI(main_gui)
