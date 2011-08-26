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
from gobject import timeout_add
from os.path import join

from general_dialogs import Notification_Dialog
from guiutils import new_scrollarea, GUI_Page
from pathname import get_dir, ICON_DIR
from plugins import get_plugin_by_type
from proximateprotocol import PLUGIN_TYPE_NOTIFICATION, PLUGIN_TYPE_COMMUNITY
from utils import iso_date_time
from gui_user import get_user_profile_picture

class Notification_GUI(GUI_Page):
    
    ICON = '64px-notification.png'
    INFORMATION = '32px-notification_information.png'
    IMPORTANT = '32px-notification_important.png'
    CLOSE_ICON = '48px-messaging_close.png'

    COL_ICON = 0
    COL_MSG = 1
    COL_CB = 2
    COL_CTX = 3
    # only in the notiifcation list:
    COL_APPLY = 4
    COL_CANCEL = 5

    def __init__(self, gui):
        GUI_Page.__init__(self, 'Notifications')
        self.main_gui = gui
        self.queue = []
        self.queue_highpri = []
        self.atbottom = True
        self.notification_plugin = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)

        self.dialog = gtk.Dialog('Proximate', gui.get_main_window(), gtk.DIALOG_DESTROY_WITH_PARENT)
        self.dialog.add_events(gtk.gdk.BUTTON_PRESS_MASK)
        self.dialog.set_position(gtk.WIN_POS_CENTER_ON_PARENT)
        self.dialog.set_default_size(200, 150)
        self.dialog.set_has_separator(False)
        self.text = gtk.Label()
        self.text.set_line_wrap(True)
        self.dialog.vbox.pack_start(self.text)
        self.dialog.connect('button-press-event', self.dialog_clicked)
        self.dialog.connect('delete-event', self.dialog_deleted)
        self.dialog.connect('response', self.response_handler)

        self.notebook = gtk.Notebook()
        self.events_label = gtk.Label('Events')
        self.notifications_label = gtk.Label('Notifications')

        # The other notification log display
        # store = (icon, message, callback, ctx, apply_icon, cancel_icon)
        self.notification_list = gtk.ListStore(gtk.gdk.Pixbuf, str, object, object, gtk.gdk.Pixbuf, gtk.gdk.Pixbuf)

        self.notification_view = gtk.TreeView(self.notification_list)
        self.notification_view.set_headers_visible(False)
        self.notification_view.connect('row-activated', self.notification_row_activated_cb)

        cr_icon = gtk.CellRendererPixbuf()
        cr_msg = gtk.CellRendererText()
        cr_apply_icon = gtk.CellRendererPixbuf()
        cr_cancel_icon = gtk.CellRendererPixbuf()

        column = gtk.TreeViewColumn('')
        column.pack_start(cr_icon, False)
        column.pack_start(cr_msg)
        column.add_attribute(cr_icon, 'pixbuf', self.COL_ICON)
        column.add_attribute(cr_msg, 'text', self.COL_MSG)
        column.set_expand(True)
        self.notification_view.append_column(column)

        self.apply_column = gtk.TreeViewColumn('')
        self.apply_column.pack_start(cr_apply_icon, False)
        self.apply_column.add_attribute(cr_apply_icon, 'pixbuf', self.COL_APPLY)
        self.notification_view.append_column(self.apply_column)

        self.cancel_column = gtk.TreeViewColumn('')
        self.cancel_column.pack_start(cr_cancel_icon, False)
        self.cancel_column.add_attribute(cr_cancel_icon, 'pixbuf', self.COL_CANCEL)
        self.notification_view.append_column(self.cancel_column)

        scrollwin = new_scrollarea()
        scrollwin.add(self.notification_view)
        self.notebook.append_page(scrollwin, self.notifications_label)

        # Event log display
        self.event_list = gtk.ListStore(gtk.gdk.Pixbuf, str, object, object)

        self.event_view = gtk.TreeView(self.event_list)
        self.event_view.set_headers_visible(False)
        self.event_view.connect('row-activated', self.event_row_activated_cb)

        cell_pic = gtk.CellRendererPixbuf()
        cell_msg = gtk.CellRendererText()

        column = gtk.TreeViewColumn('')
        column.pack_start(cell_pic, False)
        column.pack_start(cell_msg)
        column.add_attribute(cell_pic, 'pixbuf', self.COL_ICON)
        self.event_view.append_column(column)

        column.add_attribute(cell_msg, 'text', self.COL_MSG)
        scrollwin = new_scrollarea()
        scrollwin.add(self.event_view)
        scrollwin.get_vadjustment().connect('value-changed', self.event_view_scrolled)
        self.notebook.append_page(scrollwin, self.events_label)

        style = self.notification_view.get_style()
        apply_iconset = style.lookup_icon_set(gtk.STOCK_APPLY)
        self.apply_icon = apply_iconset.render_icon(style, gtk.TEXT_DIR_NONE, gtk.STATE_NORMAL, gtk.ICON_SIZE_BUTTON)
        cancel_iconset = style.lookup_icon_set(gtk.STOCK_CANCEL)
        self.cancel_icon = cancel_iconset.render_icon(style, gtk.TEXT_DIR_NONE, gtk.STATE_NORMAL, gtk.ICON_SIZE_BUTTON)

        self.connect('expose-event', self.exposed)

        self.pack_start(self.notebook)

        gui.add_page(self)
        self.show_all()

        self.active_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), self.ICON))
        self.inactive_icon = self.active_icon.copy()
        self.active_icon.saturate_and_pixelate(self.inactive_icon, 0.0, False)
        self.information_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), self.INFORMATION))
        self.important_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), self.IMPORTANT))

        self.statusbar_icon = gui.add_statusbar_icon(self.inactive_icon, 'Notifications', self.statusbar_icon_clicked)

        self.notification_plugin.register_ui(self)

    def exposed(self, widget, event):
        # scroll event and notification lists down when showing
        path_last_event = len(self.event_list)
        if path_last_event != 0:
            self.event_view.scroll_to_cell(path_last_event - 1)
        path_last_notification = len(self.notification_list)
        if path_last_notification != 0:
            self.notification_view.scroll_to_cell(path_last_notification - 1)

    def dialog_clicked(self, widget, event, data=None):
        self.notification_hide()

    def response_handler(self, dialog, response_id):
        self.notification_hide()
        return False

    def dialog_deleted(self, dialog, event):
        return True

    def close(self, widget, event):
        self.main_gui.hide_page(self)

    def event_view_scrolled(self, vadj):
        bottom = vadj.upper - vadj.step_increment - vadj.page_size
        self.atbottom = (vadj.value >= bottom)

    def append_log(self, msg, highpri, icon, cb, ctx=None):
        if icon == None:
            if highpri:
                icon = self.important_icon
            else:
                icon = self.information_icon
        else:
            icon = icon.scale_simple(32, 32, gtk.gdk.INTERP_BILINEAR)

        msg = '%s: %s' %(iso_date_time(), msg)
        msg = self.main_gui.pretty_line(msg)
        riter = self.event_list.append((icon, msg, cb, ctx))
        if self.atbottom:
            self.event_view.scroll_to_cell(self.event_list.get_path(riter))

    def notification_show(self, msg, highpri, delay, user):
        if delay == None:
            delay = 3000
        if user == None:
            self.append_log(msg, highpri, None, None)
        else:
            icon = get_user_profile_picture(user).scale_simple(32, 32, gtk.gdk.INTERP_BILINEAR)
            self.append_log(msg, highpri, icon, self.user_clicked, user)
        if highpri:
            self.queue_highpri.insert(0, msg)
            self.update_dialog()
            timeout_add(delay, self.next_highpri)
        else:
            self.queue.append(msg)
            self.update_progress_bar()
            timeout_add(delay, self.next)

    def user_clicked(self, user):
        self.community.community_gui.show_user_page(user)

    def event_row_activated_cb(self, treeview, path, view_column):
        store = treeview.get_model()
        row = store[path]

        msg = row[self.COL_MSG]
        callback = row[self.COL_CB]
        ctx = row[self.COL_CTX]

        if callback != None:
            callback(ctx)

    def notification_row_activated_cb(self, treeview, path, view_column):
        store = treeview.get_model()
        row = store[path]

        msg = row[self.COL_MSG]
        callback = row[self.COL_CB]
        ctx = row[self.COL_CTX]

        if view_column == self.cancel_column:
            handled = callback(self.notification_plugin.RESPONSE_DELETED, msg, ctx)
            store.remove(row.iter)
        elif view_column == self.apply_column:
            handled = callback(self.notification_plugin.RESPONSE_ACTIVATED, msg, ctx)
            if handled:
                store.remove(row.iter)

    def notification_with_response_show(self, msg, response_handler, ctx):
        msg = self.main_gui.pretty_line(msg)
        self.notification_list.append([self.active_icon, msg, response_handler, ctx, self.apply_icon, self.cancel_icon])
        if self.main_gui.get_current_page() != self:
            self.statusbar_icon_change(True)

        visible = (self.main_gui.get_current_page() == self and self.main_gui.has_focus())
        return visible

    def notification_hide(self):
        self.dialog.hide()

    def statusbar_clear(self):
        self.main_gui.main_progress_bar.set_text('')

    def next(self):
        if self.pop(self.queue):
            self.update_progress_bar()
        else:
            self.statusbar_clear()
        return False

    def next_highpri(self):
        if self.pop(self.queue_highpri):
            self.update_dialog()
        else:
            self.notification_hide()
        return False
        
    def pop(self, queue):
        if len(queue) > 0:
            queue.pop(0)
        return len(queue) > 0

    def update_progress_bar(self):
        self.main_gui.main_progress_bar.set_text(self.queue[0].split('\n')[0])

    def update_dialog(self):
        self.text.set_text('\n\n'.join(
            map(lambda s: s.split('\n')[0], self.queue_highpri[:3])))
        self.dialog.show_all()
    
    def ok_dialog(self, headline, msg, destroy_cb=None, parent=None, modal=False):
        self.append_log(msg, True, None, None)
        if not parent:
            parent = self.main_gui.get_main_window()
        return Notification_Dialog(parent, headline, msg, destroy_cb, modal)

    def statusbar_icon_change(self, active):
        image =  self.statusbar_icon.get_children()[0]
        if active:
            image.set_from_pixbuf(self.active_icon)
        else:
            image.set_from_pixbuf(self.inactive_icon)

    def display_window(self):
        self.main_gui.show_page(self)
        if self.atbottom and len(self.event_list) > 0:
            lastrow = self.event_list[-1]
            self.event_view.scroll_to_cell(self.event_list.get_path(lastrow.iter))
        self.statusbar_icon_change(False)

    def statusbar_icon_clicked(self):
        if self.is_visible:
            self.main_gui.hide_page(self)
        else:
            self.display_window()

def init_ui(main_gui):
    Notification_GUI(main_gui)
