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
from os.path import basename, join, isfile

from pathname import ICON_DIR, get_dir
from support import warning
from plugins import Plugin, get_plugin_by_type
from proximateprotocol import PLUGIN_TYPE_COMMUNITY, PLUGIN_TYPE_NOTIFICATION, \
    PLUGIN_TYPE_FILE_TRANSFER, PLUGIN_TYPE_FILE_SHARING
from guiutils import new_scrollarea, GUI_Page
from openfile import open_file, open_with_file_manager
from guihandler import STATUSBAR_ICON_SIZE
from utils import cut_text, ETA

MAX_TITLE = 48

class ProgressCellRenderer(gtk.GenericCellRenderer):
    __gproperties__ = {
        'percent': (gobject.TYPE_INT, 'Percent', 'Progress percentage',
                    0, 100, 0, gobject.PARAM_READWRITE),
    }

    def __init__(self):
        self.__gobject_init__()
        self.percent = 0

    def do_set_property(self, pspec, value):
        setattr(self, pspec.name, value)

    def do_get_property(self, pspec):
        return getattr(self, pspec.name)

    def on_render(self, window, widget, background_area, cell_area, expose_area, flags):
        _, _, width, height = self.on_get_size(widget, cell_area)
        context = window.cairo_create()
        context.set_source_color(widget.get_style().bg[gtk.STATE_NORMAL])
        context.rectangle(cell_area.x, cell_area.y, width, height)
        context.fill()
        context.set_source_color(widget.get_style().bg[gtk.STATE_SELECTED])
        context.rectangle(cell_area.x+2, cell_area.y+2, (width-4) * self.percent // 100, height-4)
        context.fill()

    def on_get_size(self, widget, cell_area):
        if cell_area:
            width = cell_area.width
            height = cell_area.height
        else:
            width = self.get_property('width')
            height = self.get_property('height')
            # default size
            if width == -1:
                width = 100
            if height == -1:
                height = 30
        return 0, 0, width, height

gobject.type_register(ProgressCellRenderer)

class File_Transfer_Plugin(Plugin):
    """FileTransferGui forms a window for active file transfers.
    Construct it from the main gui when the first transfer starts
    and destroy it when they're all done.

    """

    STATUSBAR_ICON = 'transfer_status_icon.png'
    CLOSE_ICON = '48px-messaging_close.png'

    COL_ICON = 0
    COL_MSG = 1
    COL_PROG = 2
    COL_TRANSFER = 3
    COL_DELETE = 4

    def __init__(self, gui):
        self.register_plugin(PLUGIN_TYPE_FILE_TRANSFER)
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        self.notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)
        self.filesharing = get_plugin_by_type(PLUGIN_TYPE_FILE_SHARING)

        self.main_gui = gui
        self.ft_statusbar_icon = gtk.gdk.pixbuf_new_from_file_at_size(join(get_dir(ICON_DIR), self.STATUSBAR_ICON), STATUSBAR_ICON_SIZE, STATUSBAR_ICON_SIZE)
        self.ft_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), self.STATUSBAR_ICON))

        self.statusbar_icon = None

        self.page = GUI_Page('File transfers')
        self.main_vbox = gtk.VBox()

        # Top row
        top_hbox = gtk.HBox()
        headline = gtk.Label('File Transfers')
        close_eb = gtk.EventBox()
        close_img = gtk.Image()
        close_eb.add(close_img)
        close_img.set_from_file(join(get_dir(ICON_DIR), self.CLOSE_ICON))
        top_hbox.pack_start(headline)
        top_hbox.pack_end(close_eb, expand = False)
        self.main_vbox.pack_start(top_hbox, False, False)

        # store = (icon, message, transfer, delete_icon)
        self.transfer_list = gtk.ListStore(gtk.gdk.Pixbuf, str, int, object, gtk.gdk.Pixbuf)

        cr_icon = gtk.CellRendererPixbuf()
        cr_msg = gtk.CellRendererText()
        cr_prog = ProgressCellRenderer()
        cr_delete_icon = gtk.CellRendererPixbuf()

        self.transfer_view = gtk.TreeView(self.transfer_list)
        self.transfer_view.set_headers_visible(False)
        self.transfer_view.connect('row-activated', self.row_activated_cb)

        column = gtk.TreeViewColumn('')
        column.pack_start(cr_icon, False)
        column.pack_start(cr_msg)
        column.add_attribute(cr_icon, 'pixbuf', self.COL_ICON)
        column.add_attribute(cr_msg, 'text', self.COL_MSG)
        column.set_expand(True)
        self.transfer_view.append_column(column)

        column = gtk.TreeViewColumn('')
        column.pack_start(cr_prog)
        column.add_attribute(cr_prog, 'percent', self.COL_PROG)
        self.transfer_view.append_column(column)

        self.delete_column = gtk.TreeViewColumn('')
        self.delete_column.pack_start(cr_delete_icon, False)
        self.delete_column.add_attribute(cr_delete_icon, 'pixbuf', self.COL_DELETE)
        self.transfer_view.append_column(self.delete_column)

        scrollwin = new_scrollarea()
        scrollwin.add(self.transfer_view)
        self.main_vbox.pack_start(scrollwin, True, True)

        style = self.transfer_view.get_style()
        abort_iconset = style.lookup_icon_set(gtk.STOCK_CLOSE)
        self.abort_icon = abort_iconset.render_icon(style, gtk.TEXT_DIR_NONE, gtk.STATE_NORMAL, gtk.ICON_SIZE_BUTTON)
        delete_iconset = style.lookup_icon_set(gtk.STOCK_DELETE)
        self.delete_icon = delete_iconset.render_icon(style, gtk.TEXT_DIR_NONE, gtk.STATE_NORMAL, gtk.ICON_SIZE_BUTTON)

        self.statusLabel = gtk.Label('')
        self.statusLabel.set_padding(3, 3)
        self.abort_all = gtk.Button('Abort all')
        self.delete_all = gtk.Button('Delete all')
        self.open_dldir = gtk.Button('Open download directory')

        status_hbox = gtk.HBox()
        status_hbox.set_size_request(-1, 50)
        status_hbox.pack_start(self.statusLabel, True, True)
        status_hbox.pack_start(self.open_dldir, False, False, padding = 5)
        status_hbox.pack_start(self.delete_all, False, False, padding = 5)
        status_hbox.pack_start(self.abort_all, False, False, padding = 5)
        self.main_vbox.pack_start(status_hbox, False, False)

        # callbacks
        self.delete_all.connect('clicked', self.delete_all_cb)
        self.abort_all.connect('clicked', self.abort_all_cb)
        self.open_dldir.connect('clicked', self.open_dldir_cb)
        close_eb.connect('button-press-event', self.close_cb)

        self.page.pack_start(self.main_vbox)
        self.page.show_all()
        self.main_gui.add_page(self.page)

    def row_activated_cb(self, treeview, path, view_column):
        row = self.transfer_list[path]

        transfer = row[self.COL_TRANSFER]

        if view_column == self.delete_column:
            transfer.clicked()

    def abort_all_cb(self, widget, data = None):
        for row in self.transfer_list:
            transfer = row[self.COL_TRANSFER]
            transfer.abort()

    def delete_all_cb(self, widget, data = None):
        for row in self.transfer_list:
            transfer = row[self.COL_TRANSFER]
            transfer.delete()

    def open_dldir_cb(self, widget, data=None):
        open_with_file_manager(self.filesharing.get_download_path())

    def close_cb(self, widget, event):
        if self.page.is_visible:
            self.main_gui.hide_page(self.page)

        if self.statusbar_icon != None:
            self.main_gui.remove_statusbar_icon(self.statusbar_icon)
            self.statusbar_icon = None
        return True

    def open_filetransfergui(self):
        if self.statusbar_icon == None:
            self.statusbar_icon = self.main_gui.add_statusbar_icon(self.ft_statusbar_icon, 'File Transfers', self.statusbar_icon_clicked)

    def statusbar_icon_clicked(self):
        if self.page.is_visible:
            self.main_gui.hide_page(self.page)
        else:
            self.main_gui.show_page(self.page)

    def add_transfer(self, title, size, abort_cb, ctx=None, silent=False):
        self.open_filetransfergui()

        title = cut_text(title, MAX_TITLE)

        # popping up the transfer notification window, that returns
        # a handel to a function advancing its progressbar
        dialog = None
        if not silent:
            dialog = Transfer_Dialog(self.main_gui.get_main_window(), title, abort_cb, ctx)

        transfer = Transfer_Item(self, title, size, abort_cb, ctx, dialog)
        riter = self.transfer_list.append([self.ft_icon, title, 0, transfer, self.abort_icon])
        transfer.iter = riter

        return transfer

class Transfer_Item:
    def __init__(self, ui, title, size, abort_cb, ctx, dialog):
        self.ui = ui
        self.title = title
        self.abort_cb = abort_cb
        self.ctx = ctx
        self.iter = None
        self.dialog = dialog
        self.finished = False
        self.eta = None
        self.eta = ETA(size)

    def update(self, increment):
        eta = self.eta.update(increment)
        if self.dialog != None:
            self.dialog.update(eta)

        (seconds_left, v, progress) = eta
        if progress != None:
            text = "%s\n%s sec remaining" % (self.title, str(seconds_left))
            self.ui.transfer_list.set_value(self.iter, self.ui.COL_MSG, text)
            self.ui.transfer_list.set_value(self.iter, self.ui.COL_PROG, int(progress * 100))

    def cleanup(self, msg):
        if self.dialog != None:
            self.dialog.cleanup(msg)

        text = "%s\n%s" % (self.title, msg)
        self.ui.transfer_list.set_value(self.iter, self.ui.COL_MSG, text)
        self.ui.transfer_list.set_value(self.iter, self.ui.COL_PROG, 100)
        self.ui.transfer_list.set_value(self.iter, self.ui.COL_DELETE, self.ui.delete_icon)
        self.finished = True

    def abort(self):
        if not self.finished:
            self.abort_cb(self.ctx)

    def delete(self):
        if self.finished:
            self.ui.transfer_list.remove(self.iter)

    def clicked(self):
        if not self.finished:
            self.abort()
        else:
            self.delete()

class Transfer_Dialog:
    """
    Notification window that pops up to the screen when the transfer
    starts.
    """

    CLOSE_ICON = '48px-messaging_close.png'

    def __init__(self, main_gui_window, title, abort_cb, ctx):
        headline = 'File transfer'

        self.filesharing = get_plugin_by_type(PLUGIN_TYPE_FILE_SHARING)

        self.base = gtk.Dialog(headline, main_gui_window, \
                               gtk.DIALOG_DESTROY_WITH_PARENT)

        self.abort_cb = abort_cb
        self.ctx = ctx
        self.title = title
        self.text = gtk.Label(title)
        self.pbar = gtk.ProgressBar()

        # Open download directory -button
        self.open_dldir = gtk.Button('Open download directory')
        self.open_dldir.connect('clicked', self.open_dldir_cb)

        # Hide button
        close_label = gtk.Label("Hide:")
        close_eb = gtk.EventBox()
        close_hbox = gtk.HBox()
        close_img = gtk.Image()
        close_eb.add(close_hbox)
        close_img.set_from_file(join(get_dir(ICON_DIR), self.CLOSE_ICON))

        # Abort button
        self.abort_button = gtk.Button('Cancel')
        self.abort_button.connect('clicked', self.abort_cb)

        close_hbox.pack_start(close_label)
        close_hbox.pack_start(close_img)

        close_eb.connect('button-press-event', self.close_cb)

        self.pbar.set_text('Starting transfer...')

        self.base.vbox.pack_start(self.text)
        self.base.vbox.pack_start(self.pbar)
        self.base.action_area.pack_end(self.open_dldir, expand=False)
        self.base.action_area.pack_end(self.abort_button, expand=False)
        self.base.action_area.pack_end(close_eb, expand=False)

        self.base.show_all()

    def update(self, eta):
        (seconds_left, v, progress) = eta
        if progress != None:
            text = "%s sec remaining" % str(seconds_left)
            self.pbar.set_text(text)
            self.pbar.set_fraction(progress)

    def cleanup(self, msg):
        self.pbar.set_text(msg)
        self.pbar.set_fraction(1)
        self.abort_button.set_sensitive(False)

    def open_dldir_cb(self, widget, param=None):
        open_with_file_manager(self.filesharing.get_download_path())

    def close_cb(self, widget, event):
        self.base.destroy()

    def abort_cb(self, widget):
        if self.abort_cb != None:
            self.abort_cb(ctx)

def init_ui(main_gui):
    File_Transfer_Plugin(main_gui)
