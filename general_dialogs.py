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

from plugins import get_plugin_by_type
from proximateprotocol import PLUGIN_TYPE_FILE_SHARING
from file_chooser_dlg import File_Chooser, FILE_CHOOSER_TYPE_DIR

class Notification_Queue:
    """
    Queue for simple notifications.
    Shows them at most three at a time in a self disappearing dialog.
    """

    def __init__(self, main_gui_window):
        self.queue = []
        self.dialog = gtk.Dialog('Proximate', main_gui_window,
            gtk.DIALOG_DESTROY_WITH_PARENT)
        self.dialog.set_position(gtk.WIN_POS_CENTER_ON_PARENT)
        self.dialog.set_default_size(200, 150)
        self.dialog.set_has_separator(False)
        self.text = gtk.Label()
        self.text.set_line_wrap(True)
        self.dialog.vbox.pack_start(self.text)

    def push(self, text, highpri):
        text = text.split('\n')[0]
        if highpri:
            self.queue.insert(0, text)
        else:
            self.queue.append(text)
        self.show_text()
        timeout = gobject.timeout_add(3000, self.pop)
        self.dialog.show_all()

    def pop(self):
        self.queue.pop(0)
        if len(self.queue) > 0:
            self.show_text()
        else:
            self.dialog.hide()
        return False

    def show_text(self):
        self.text.set_text('\n\n'.join(self.queue[:3]))

class Notification:
    """
    This is a simple notification, that pops up to the screen, and disappears
    after little time.
    """

    def __init__(self, main_gui_window, headline, text, time_visible_ms = 3000):
        self.base = gtk.Dialog(headline, main_gui_window, \
                               gtk.DIALOG_DESTROY_WITH_PARENT)
        self.base.add_events(gtk.gdk.BUTTON_PRESS_MASK)

        self.text = gtk.Label(text)
        self.base.vbox.pack_start(self.text)
        self.close_timeout = gobject.timeout_add(time_visible_ms, self.close)
        self.base.connect("button-press-event", self.close)
        
        self.base.show_all()

    def close(self, widget = None, data = None):
        self.base.destroy()

class Notification_Dialog:
    """
    This dialog notifys the user about something, and destroys itself
    when the OK button is pressed.
    """
    def __init__(self, main_gui_window, headline, text, destroy_cb = None, modal=False):

        # this is used to remove dialog's reference from parents list
        self.destroy_cb = destroy_cb

        self.base = gtk.Dialog(headline, main_gui_window, \
                               gtk.DIALOG_DESTROY_WITH_PARENT, \
                               (gtk.STOCK_OK, gtk.RESPONSE_OK))
        self.base.set_default_size(300, -1)
        self.text = gtk.Label(text)
        self.base.vbox.pack_start(self.text)

        if modal:
            self.base.set_modal(True)

        self.base.connect("response", self.close)
        self.base.show_all()

    def __del__(self):
        """ Dirty workaround, otherwise instance seems to go away magically """
        pass

    def close(self, widget = None, data = None):
        if self.destroy_cb != None:
            self.destroy_cb(self)
        self.base.destroy()

class Approve_Deny_Dialog:
    """
    This dialog asks the given question, and calls given callback
    function with true or false. It's also possible to relay data.
    """

    def __init__(self, main_gui_window, headline, text, cb, data=None):
        self.callback = cb
        self.data = data

        self.base = gtk.Dialog(headline, main_gui_window, \
                               gtk.DIALOG_DESTROY_WITH_PARENT, \
                               (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT, \
                                gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
        self.text = gtk.Label(text)
        self.text.set_line_wrap(gtk.WRAP_WORD)
        self.base.vbox.pack_start(self.text)

        self.base.connect("response", self.response_cb)

        self.base.show_all()

    def __del__(self):
        """ Dirty workaround, otherwise instance seems to go away magically """
        pass

    def response_cb(self, widget, response_id, *args):
        if response_id == gtk.RESPONSE_ACCEPT:
            self.callback(True, self.data)
        else:
            self.callback(False, self.data)

        self.base.destroy()
        return True

class Approve_Deny_Dialog_2:
    """ Call .run() method after creation """

    def __init__(self, parenproximatedow, headline, msg, modal=False):
        flags = gtk.DIALOG_DESTROY_WITH_PARENT
        if modal:
            flags |= gtk.DIALOG_MODAL
        self.dlg = gtk.Dialog(headline, parenproximatedow, flags,
                              (gtk.STOCK_NO, gtk.RESPONSE_NO,
                               gtk.STOCK_YES, gtk.RESPONSE_YES))
        text = gtk.Label(msg)
        text.set_line_wrap(gtk.WRAP_WORD)
        self.dlg.vbox.pack_start(text)
        self.dlg.show_all()

    def run(self):
        response = self.dlg.run()
        self.dlg.destroy()
        return response == gtk.RESPONSE_YES

class Download_Dialog(gtk.Dialog):
    """ Dialog to select the default download directory

        callback(accept, open_content, ctx) """

    def __init__(self, main_gui_window, title, descr, cb, ctx = None):
        self.cb = cb
        self.ctx = ctx

        self.filesharing = get_plugin_by_type(PLUGIN_TYPE_FILE_SHARING)

        gtk.Dialog.__init__(self, title, main_gui_window,
            gtk.DIALOG_DESTROY_WITH_PARENT, ('Download', 1, 'Open', 2, 'Cancel', 3))

        self.main_gui_window = main_gui_window
        down_dir = self.filesharing.get_download_path()
        descr_text = gtk.Label(descr)
        self.directory_entry = gtk.Entry()
        self.vbox.pack_start(descr_text, False, False)
        help_text = gtk.Label('Save to:')
        self.directory_entry = gtk.Entry()
        self.vbox.pack_start(help_text, False, False)
        hbox = gtk.HBox()
        self.vbox.pack_start(hbox)
        self.directory_entry.set_text(down_dir)
        self.chooser_button = gtk.Button('Select directory')
        self.chooser_button.connect('clicked', self.open_chooser)
        hbox.pack_start(self.directory_entry, True, True, 10)
        hbox.pack_start(self.chooser_button, False, False)

        self.connect('response', self.handle_response)

        self.show_all()

    def open_chooser(self, widget):
        chooser_dialog = File_Chooser(self.main_gui_window, FILE_CHOOSER_TYPE_DIR, False, self.directory_changed)

    def directory_changed(self, directory, ctx):
        if directory != None:
            self.directory_entry.set_text(directory)

    def handle_response(self, widget, event):
        if event == 1:
            # Download
            down_dir = self.directory_entry.get_text()
            print down_dir
            self.filesharing.set_download_path(down_dir)
            self.cb(True, False, self.ctx)
        elif event == 2:
            # Download and Open
            down_dir = self.directory_entry.get_text()
            self.filesharing.set_download_path(down_dir)
            self.cb(True, True, self.ctx)
        else:
            self.cb(False, False, self.ctx)
        self.destroy()

class Input_Dialog(gtk.Dialog):
    """ Dialog for requesting textual input from user.
    """

    def __init__(self, main_gui_window, title, descr, cb, ctx=None):
        gtk.Dialog.__init__(self, title, main_gui_window,
            gtk.DIALOG_DESTROY_WITH_PARENT,
            (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT,
            gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))

        self.cb = cb
        self.ctx = ctx

        self.descr_label = gtk.Label(descr)
        self.vbox.pack_start(self.descr_label)
        self.text_entry = gtk.Entry()
        self.vbox.pack_start(self.text_entry, expand=False)

        self.connect('response', self.dialog_response)

        self.show_all()

    def dialog_response(self, widget, response):
        if response == gtk.RESPONSE_ACCEPT:
            self.cb(self.text_entry.get_text(), self.ctx)
        else:
            self.cb(None, self.ctx)
        self.destroy()
            
