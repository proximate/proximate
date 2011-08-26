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
import pango
from os.path import join

from communitymeta import Community
from gui_user import get_user_profile_picture, get_community_icon
from guiutils import new_scrollarea, GUI_Page
from messaging import user_from_addr, decode_addr
from plugins import get_plugin_by_type
from pathname import get_dir, ICON_DIR
from support import warning, get_debug_mode
from proximateprotocol import PLUGIN_TYPE_COMMUNITY, PLUGIN_TYPE_MESSAGING, \
    PLUGIN_TYPE_NOTIFICATION, TP_NICK_DEFAULT
from user import User
from utils import iso_date_time

class Messaging_GUI(GUI_Page):

    MESSAGING_ICON = '64px-messaging_icon.png'
    END_CHAT_ICON = '48px-messaging_close.png'
    TOGGLE_CHANNEL_ICON = '64px-messaging_channels.png'
    STATUSBAR_ICON = '64px-messaging_status_icon.png'
    WARNING_ICON = '32px-warning.png'

    COL_MSGID = 0
    COL_TIME = 1
    COL_NICK = 2
    COL_MESSAGE = 3
    COL_ICON = 4

    def __init__(self, gui):
        GUI_Page.__init__(self, 'Messaging')
        self.main_gui = gui
        self.toggle_dialog = None
        self.statusbar_icon = None
        self.atbottom = True

        self.active_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), self.STATUSBAR_ICON))
        self.inactive_icon = self.active_icon.copy()
        self.active_icon.saturate_and_pixelate(self.inactive_icon, 0.0, False)

        # GUI stores liststores and buttos as (store, button) tuples indexed
        # by Conversation
        self.gui_storebutton = {}

        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        self.messaging = get_plugin_by_type(PLUGIN_TYPE_MESSAGING)
        self.notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)

        # the currently active conversation
        self.active_conversation = None

        messaging_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), self.MESSAGING_ICON))

        self.community.community_gui.register_user_event(messaging_icon, 'Chat', self.start_messaging_cb)
        self.community.community_gui.register_com_event(messaging_icon, 'Chat', self.start_messaging_cb)

        self.right_vbox = gtk.VBox()
        self.left_vbox = gtk.VBox()
        vseparator = gtk.VSeparator()
        self.pack_start(self.left_vbox, False, True)
        self.pack_start(vseparator, False, False)
        self.pack_start(self.right_vbox, True, True)
        self.top_hbox = gtk.HBox()
        separator1 = gtk.HSeparator()
        scrollwin = new_scrollarea()
        separator2 = gtk.HSeparator()
        self.bottom_hbox = gtk.HBox()

        # adding top level
        self.right_vbox.pack_start(self.top_hbox, expand = False)
        self.right_vbox.pack_start(separator1, expand = False)
        self.right_vbox.pack_start(scrollwin)
        self.right_vbox.pack_end(self.bottom_hbox, expand = False)
        self.right_vbox.pack_end(separator2, expand = False)

        # creatind the top row
        self.headline = gtk.Label()
        self.end_chat_eb = gtk.EventBox()
        self.end_chat_img = gtk.Image()

        # setting up the button icons in the top row
        self.end_chat_eb.add(self.end_chat_img)
        self.end_chat_img.set_from_file(join(get_dir(ICON_DIR), self.END_CHAT_ICON))

        # forming the top row
        self.top_hbox.pack_start(self.headline)
        self.top_hbox.pack_end(self.end_chat_eb, expand = False)

        # creating the chat area
        cr_icon = gtk.CellRendererPixbuf()
        self.chat_tw = gtk.TreeView()
        self.chat_tw_cr1 = gtk.CellRendererText()
        self.chat_tw_cr2 = gtk.CellRendererText()
        self.chat_tw_cr3 = gtk.CellRendererText()

        column = gtk.TreeViewColumn('Time')
        column.pack_start(cr_icon)
        column.pack_start(self.chat_tw_cr1)
        column.add_attribute(cr_icon, "pixbuf", self.COL_ICON)
        column.add_attribute(self.chat_tw_cr1, "text", self.COL_TIME)
        self.chat_tw.append_column(column)

        self.nick_column = gtk.TreeViewColumn('Nick')
        self.nick_column.pack_start(self.chat_tw_cr2)
        self.nick_column.add_attribute(self.chat_tw_cr2, "text", self.COL_NICK)
        self.chat_tw.append_column(self.nick_column)

        column = gtk.TreeViewColumn('Message')
        column.pack_start(self.chat_tw_cr3)
        column.add_attribute(self.chat_tw_cr3, "text", self.COL_MESSAGE)
        self.chat_tw.append_column(column)

        # to keep the fields aligned to the top of each row
        self.chat_tw_cr1.set_property('yalign', 0.0)
        self.chat_tw_cr2.set_property('yalign', 0.0)
        self.chat_tw_cr3.set_property('yalign', 0.0)

        self.chat_tw_cr3.set_property('wrap-mode', pango.WRAP_WORD_CHAR)
        self.chat_tw.set_property('enable-search', False)
        self.chat_tw.set_property('headers-visible', False)
        self.chat_tw.connect('size-allocate', self.resized)
        self.chat_tw.connect('row-activated', self.chat_row_activated_cb)

        scrollwin.add(self.chat_tw)
        scrollwin.get_vadjustment().connect('value-changed', self.chat_tw_scrolled)

        # creating the left area for chat tabs
        self.left_vbox.set_size_request(200, -1)
        chatlist_label = gtk.Label('Active chats')
        self.left_vbox.pack_start(chatlist_label, False, True)
        self.chatlist_scroll = new_scrollarea()
        self.left_vbox.pack_start(self.chatlist_scroll, True, True)
        self.chatlist = gtk.VBox()
        self.chatlist.set_size_request(200-2, -1)
        self.chatlist_scroll.add_with_viewport(self.chatlist)

        # creating the bottom area
        self.entry = gtk.Entry()
        self.bottom_hbox.pack_start(self.entry)

        self.show_all()
        gui.add_page(self)

        style = self.headline.get_style()
        self.normal_text_color = style.fg[gtk.STATE_NORMAL].copy()

        self.warning_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), self.WARNING_ICON))

        # callbacks:
        # connecting press of enter to sending message
        self.entry.connect('activate', self.entry_activate_cb)
        self.end_chat_eb.connect('button-press-event', self.close_active_conversation_cb)

        # monitor chat page visibility
        self.connect('expose-event', self.exposed)

        self.messaging.register_ui(self)

    def exposed(self, widget, event):
        # scroll to bottom
        store, button = self.get_storebutton(self.active_conversation)
        path_last = len(store)
        if path_last != 0 and self.atbottom:
            self.chat_tw.scroll_to_cell(len(store) - 1)

    def chat_tw_scrolled(self, vadj):
        self.atbottom = (vadj.page_size + vadj.value >= vadj.upper)

    def chat_row_activated_cb(self, treeview, path, view_column):
        if view_column != self.nick_column:
            return
        store, button = self.get_storebutton(self.active_conversation)
        row = store[path]

        msgid = row[self.COL_MSGID]
        msg = self.active_conversation.get_msg(msgid)
        sender_addr = msg.get_sender_addr()
        user = user_from_addr(self.community, sender_addr, safe=False)
        self.community.community_gui.show_user_page(user)

    def resized(self, view, rect):
        store = view.get_model()
        if store == None:
            return

        desc_column = view.get_column(2)
        columns_width = 0
        for col in view.get_columns()[:-1]:
            columns_width += col.get_width()
        if rect.width < columns_width:
            return
        wrap_width = rect.width - columns_width
        desc_column.get_cell_renderers()[0].set_property('wrap-width', wrap_width)
        desc_column.set_property('max-width', wrap_width)

        i = store.get_iter_first()
        while i and store.iter_is_valid(i):
                store.row_changed(store.get_path(i), i)
                i = store.iter_next(i)
                view.set_size_request(0, -1)

    def start_messaging_cb(self, target):
        if isinstance(target, User):
            self.start_messaging_u2u_cb(target)
        elif isinstance(target, Community):
            self.start_messaging_com_cb(target)

    def start_messaging_u2u_cb(self, user):
        # notify user if we are trying to chat with ourself
        if user == self.community.get_myself():
            self.notification.notify("Error: Trying to chat with yourself", highpri=True)
            return
        self.start_messaging(user, False)

    def start_messaging_com_cb(self, community):
        if not community.get('peer'):
            self.notification.notify("Personal community chat not implemented", highpri=True)
            return
        self.start_messaging(community, True)

    # starts messaging with target
    def start_messaging(self, target, is_community):
        if is_community:
            c = self.messaging.open_community_conversation(target)
        else:
            c = self.messaging.open_user_conversation(target)

        if not self.has_storebutton(c):
            self.new_storebutton(c)
        self.set_active_conversation(c)

        # show messaging GUI
        self.main_gui.show_page(self)
        if self.statusbar_icon == None:
            self.statusbar_icon = self.main_gui.add_statusbar_icon(self.inactive_icon, 'Chat', self.statusbar_icon_clicked)
        self.set_statusbar_icon_status(False)

    def entry_activate_cb(self, data=None):
        message = self.entry.get_text()
        self.entry.set_text('')
        if len(message) > 0:
            self.messaging.say(self.active_conversation, message)

    def statusbar_icon_clicked(self):
        if self.is_visible:
            self.main_gui.hide_page(self)
        else:
            self.main_gui.show_page(self)
            self.set_statusbar_icon_status(False)

    def close_chat_cb(self, widget=None, event=None):
        if self.is_visible:
            self.main_gui.hide_page(self)

        # remove chat icon from statusbar
        if self.statusbar_icon != None:
            self.main_gui.remove_statusbar_icon(self.statusbar_icon)
            self.statusbar_icon = None

        # remove stores and buttons
        open_conversations = self.gui_storebutton.keys()
        if open_conversations:
            for c in open_conversations:
                self.remove_storebutton(c)

        # close Conversations
        self.messaging.close_all_conversations()

    def has_storebutton(self, conversation):
        assert(conversation != None)
        return conversation in self.gui_storebutton

    def new_storebutton(self, conversation):
        # NOTE: msgid column is of type gobject.TYPE_PYOBJECT because
        # glib strings are not binary safe
        assert(conversation != None)
        store = gtk.ListStore(object, str, str, str, gtk.gdk.Pixbuf)
        button = self.add_chat_button(conversation)
        self.gui_storebutton[conversation] = (store, button)
        return (store, button)

    def get_storebutton(self, conversation):
        return self.gui_storebutton[conversation]

    def remove_storebutton(self, conversation):
        self.remove_chat_button(conversation)
        self.gui_storebutton.pop(conversation)

    def close_active_conversation_cb(self, widget=None, event=None):
        self.remove_storebutton(self.active_conversation)
        self.messaging.close_conversation(self.active_conversation)

        open_conversations = self.gui_storebutton.keys()
        if len(open_conversations) > 0:
            self.set_active_conversation(open_conversations[0])
        else:
            self.active_conversation = None
            self.close_chat_cb()

    def new_message_cb(self, conversation, msg):
        sender_addr = msg.get_sender_addr()
        # safe == False because messages sent by me also go through this path
        sender = user_from_addr(self.community, sender_addr, safe=False)
        if sender:
            sender_nick = sender.get('nick')
            if get_debug_mode() and sender.get('hops') != None:
                sender_nick += ':%d' % sender.get('hops')
        else:
            sender_nick = TP_NICK_DEFAULT

        if not self.has_storebutton(conversation):
            store, button = self.new_storebutton(conversation)
            if conversation.is_community():
                notificationmsg = 'Chat activity on %s community' % conversation.tag()
                self.notification.notify(notificationmsg)
            else:
                self.notification.user_notify(sender, 'has spoken to you')
        else:
            store, button = self.get_storebutton(conversation)

        ctime = int(msg.get_ctime()[0])
        tstr = iso_date_time(t=ctime, dispdate=False, dispsecs=False)

        msgid = msg.get_msgid()

        children = conversation.get_children(msgid, [])

        # NOTE: first column is of type gobject.TYPE_PYOBJECT because
        # glib strings are not binary safe
        icon = None
        if msg.error:
            icon = self.warning_icon
        row_data = [msgid, tstr, '<' + sender_nick + '> ', msg.get_msg(), icon]

        # if message has children it is sorted to the list such
        # that it is inserted before all its children
        if children:
            row = None
            for row in store:
                if row[self.COL_MSGID] in children:
                    break
            store.insert_before(row.iter, row_data)
        else:
            riter = store.append(row_data)
            if self.active_conversation == conversation and self.atbottom:
                self.chat_tw.scroll_to_cell(store.get_path(riter))

        # announce activity on conversation
        return self.activity(conversation)

    def delete_message_cb(self, conversation, msg):
        if not self.has_storebutton(conversation):
            return

        msgid = msg.get_msgid()

        store, button = self.get_storebutton(conversation)
        for row in store:
            if row[self.COL_MSGID] == msgid:
                store.remove(row.iter)
                break

    def change_message_cb(self, conversation, msg):
        if not self.has_storebutton(conversation):
            return

        msgid = msg.get_msgid()

        store, button = self.get_storebutton(conversation)
        for row in store:
            if row[self.COL_MSGID] == msgid:
                icon = None
                if msg.error:
                    icon = self.warning_icon
                row[self.COL_ICON] = icon
                break

    def add_chat_button(self, conversation):

        (is_community, key, id) = decode_addr(conversation.target_addr)

        if is_community:
            coml = self.community.find_communities(id, peer=True)
            com = None
            if len(coml) > 0:
                com = coml[0]
            name = id
        else:
            user = self.community.get_user(id)
            name = user.get('nick')

        children = self.chatlist.get_children()
        if children:
            button_group = self.chatlist.get_children()[0]
        else:
            button_group = None

        button = gtk.RadioButton(button_group, name)
        button.set_mode(False)
        self.chatlist.pack_start(button, False, True)
        button.show_all()
        button.connect('toggled', self.chat_button_toggled, conversation)

        if is_community:
            image = None
            if com != None:
                image = gtk.image_new_from_pixbuf(get_community_icon(com).scale_simple(48, 48, gtk.gdk.INTERP_BILINEAR))
        else:
            image = gtk.image_new_from_pixbuf(get_user_profile_picture(user, False).scale_simple(48, 48, gtk.gdk.INTERP_BILINEAR))

        if image != None:
            button.set_image(image)

        return button

    def remove_chat_button(self, conversation):
        store, button = self.get_storebutton(conversation)
        self.chatlist.remove(button)

    def chat_button_toggled(self, widget, conversation):
        if widget.get_active():
            self.set_active_conversation(conversation)

    def set_active_conversation(self, conversation):
        assert(conversation != None)
        if self.active_conversation == conversation:
            return

        store, button = self.get_storebutton(conversation)

        self.active_conversation = conversation
        self.chat_tw.set_model(store)
        if len(store) > 0:
            lastrow = store[-1]
            self.chat_tw.scroll_to_cell(store.get_path(lastrow.iter))
        self.atbottom = True

        if button:
            image, label = button.get_children()[0].get_children()[0].get_children()
            label.modify_fg(gtk.STATE_NORMAL, self.normal_text_color)

            if not button.get_active():
                button.set_active(True)

        self.entry.grab_focus()

    def set_statusbar_icon_status(self, active):
        # create icon if it does not exist
        if self.statusbar_icon == None:
            self.statusbar_icon = self.main_gui.add_statusbar_icon(self.inactive_icon, 'Chat', self.statusbar_icon_clicked)

        image = self.statusbar_icon.get_children()[0]
        if active:
            image.set_from_pixbuf(self.active_icon)
        else:
            image.set_from_pixbuf(self.inactive_icon)

    def activity(self, conversation):
        store, button = self.get_storebutton(conversation)

        if conversation != self.active_conversation:
            color = gtk.gdk.Color(0xffff, 0x0, 0x0)
            image, label = button.get_children()[0].get_children()[0].get_children()
            label.modify_fg(gtk.STATE_NORMAL, color)

        # if chat is non-visible change chat icon state and set
        # active conversation
        if self.main_gui.get_current_page() != self:
            self.set_statusbar_icon_status(True)
            self.set_active_conversation(conversation)

        visible = (self.main_gui.get_current_page() == self and self.main_gui.has_focus()
                   and conversation == self.active_conversation)
        return visible

def init_ui(main_gui):
    Messaging_GUI(main_gui)
