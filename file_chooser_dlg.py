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

from guiutils import new_filechooser

FILE_CHOOSER_TYPE_FILE = 0
FILE_CHOOSER_TYPE_DIR = 1

class File_Chooser:
    """ This class is used for selecting file using maemo's
    file browser.

    Can be used for selecting file or directory depending on the
    parameter type. """

    
    def __init__(self, main_window, dialog_type, multiple, cb, ctx=None):

        if dialog_type == FILE_CHOOSER_TYPE_FILE:
            dtype = gtk.FILE_CHOOSER_ACTION_OPEN
        elif dialog_type == FILE_CHOOSER_TYPE_DIR:
            dtype = gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER

        self.dlg = new_filechooser(main_window, dtype)

        self.multiple = multiple
        self.cb = cb
        self.ctx = ctx

        if self.multiple:
            self.dlg.set_select_multiple(True)

        self.dlg.set_modal(True)
        self.dlg.set_default_response(gtk.RESPONSE_OK)

        self.dlg.connect("response", self.response_handler)
        self.dlg.show()

    def response_handler(self, widget, response_id, *args):
        fname = None
        if response_id == gtk.RESPONSE_OK:
            if not self.multiple:
                fname = self.dlg.get_filename()
            else:
                fname = self.dlg.get_filenames()
        self.cb(fname, self.ctx)

        self.dlg.destroy()
        return True
    
    def add_supported_pixbuf_formats(self):
        """ Adds all pixbuf formats to FileChooserDialog """
        
        file_filter = gtk.FileFilter()
        file_filter.set_name("Images")
        file_filter.add_pixbuf_formats()
        self.dlg.add_filter(file_filter)
