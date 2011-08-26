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
import tempfile
import os

from plugins import get_plugin_by_type
from file_chooser_dlg import File_Chooser, FILE_CHOOSER_TYPE_FILE
from camera import Camera, Camera_Exception, DEFAULT_RESOLUTION
from support import warning, debug
from ossupport import xclose, xremove
from proximateprotocol import PLUGIN_TYPE_NOTIFICATION, MAX_FACE_DIMENSION, \
    TP_FACE_SIZE
from guiutils import scale_image, compress_jpeg

class Picture_Choose_Dialog:
    """ This class is used for previewing and selecting the profile picture.
    Uses File_Chooser to select the picture. """

    def __init__(self, gui, got_picture_cb):
        self.notify = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION).notify

        self.filename = None
        self.gui = gui
        self.tempfile = None # file to be removed when dialog is closed
        self.got_picture_cb = got_picture_cb

        self.dialog = gtk.Dialog("Select Profile Picture",
                        gui.get_main_window(),
                        gtk.DIALOG_DESTROY_WITH_PARENT | gtk.DIALOG_MODAL,
                        (gtk.STOCK_OK, gtk.RESPONSE_OK,
                         gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL))
        self.dialog.set_border_width(5)
        self.dialog.vbox.set_spacing(2)
        self.dialog.action_area.set_layout(gtk.BUTTONBOX_END)
        self.dialog.set_position(gtk.WIN_POS_CENTER)

        self.initialize_widgets()

        self.dialog.connect("response", self.response_handler)
        self.dialog.connect("delete-event", self.dialog_deleted)

    def initialize_widgets(self):
        self.profile_image = gtk.Image()
        self.profile_image.set_size_request(300, 300)
        self.profile_image.set_from_stock(gtk.STOCK_ORIENTATION_PORTRAIT, 4)
        self.browse_button = gtk.Button("Browse")
        self.take_photo = gtk.Button("Take photo")
        self.clear_image = gtk.Button('Clear image')

        self.vbox1 = gtk.VBox()

        self.vbox1.pack_start(self.profile_image)
        self.vbox1.pack_start(self.browse_button, False, True)
        self.vbox1.pack_start(self.take_photo, False, True)
        self.vbox1.pack_start(self.clear_image, False, True)
        self.dialog.vbox.pack_start(self.vbox1)

        self.browse_button.connect("clicked", self.browse_button_clicked)
        self.take_photo.connect("clicked", self.take_photo_clicked)
        self.clear_image.connect('clicked', self.clear_image_clicked)

    def response_handler(self, widget, response_id, *args):
        """ Handles dialog responses """

        if response_id == gtk.RESPONSE_OK:
            self.got_picture_cb(self.filename)

        self.dialog.hide()
        return True

    def dialog_deleted(self, dialog, event):
        return True

    def show(self):
        self.dialog.show_all()

    def close(self):
        self.remove_temp()
        self.dialog.destroy()
        
    def browse_button_clicked(self, widget):
        file_dlg = File_Chooser(self.gui.main_window, FILE_CHOOSER_TYPE_FILE, False, self.browse_chooser_cb)
        file_dlg.add_supported_pixbuf_formats()
        #self.dialog.hide()

    def browse_chooser_cb(self, filename, ctx):
        #self.dialog.show()

        if filename == None:
            return
        # checking if we have to scale the picture down
        # also checking if it even is a picture
        try:
            pixbuf = gtk.gdk.pixbuf_new_from_file(filename)
        except gobject.GError:
            self.notify("Error: Invalid image file", True)
            return

        larger_dimension = max((pixbuf.get_width(), pixbuf.get_height()))
        if os.path.getsize(filename) <= TP_FACE_SIZE and \
           larger_dimension <= MAX_FACE_DIMENSION:
            # use the picture directly without recompression
            self.remove_temp()
            self.set_picture(filename)
        else:
            # need to recompress the picture
            pixbuf = scale_image(pixbuf, MAX_FACE_DIMENSION)
            if not self.compress_jpeg(pixbuf):
                self.notify("Error: Unable to compress JPEG picture", True)

    def remove_temp(self):
        if self.tempfile != None:
            if not xremove(self.tempfile):
                warning("Unable to remove a scaled picture\n")
            self.tempfile = None

    def take_photo_clicked(self, widget):
        self.camera_dialog = Camera_Dialog(self.dialog, DEFAULT_RESOLUTION,
            self.got_photo)

    def got_photo(self, pixbuf):
        if pixbuf:
            pixbuf = scale_image(pixbuf, MAX_FACE_DIMENSION)
            if not self.compress_jpeg(pixbuf):
                self.notify("Error: Unable to compress JPEG picture", True)
        self.camera_dialog = None

    def clear_image_clicked(self, widget):
        self.remove_temp()
        self.set_picture(None)

    def set_picture(self, fname):
        self.filename = fname
        self.profile_image.set_from_file(fname)

    def compress_jpeg(self, pixbuf):
        (fd, filename) = tempfile.mkstemp(prefix = 'proximate-tmp-profile-pic-')
        xclose(fd)
        if not compress_jpeg(pixbuf, filename, TP_FACE_SIZE):
            return False
        self.remove_temp()
        self.tempfile = filename
        self.set_picture(filename)
        return True

class Camera_Dialog:
    def __init__(self, profile_dialog, resolution, got_photo_cb):
        self.cb = got_photo_cb
        self.dialog = gtk.Dialog('Camera', profile_dialog,
            gtk.DIALOG_DESTROY_WITH_PARENT | gtk.DIALOG_MODAL)
        self.dialog.set_has_separator(False)
        self.image = gtk.DrawingArea()
        self.image.set_size_request(resolution[0], resolution[1])
        self.help_text = gtk.Label('Click to take picture')

        try:
            self.camera = Camera(resolution, self.image)
        except Camera_Exception:
            debug('profile dialog: Unable to initialize camera\n')
            self.camera = None
            self.help_text.set_label('No camera found')

        self.image_hbox = gtk.HBox()
        self.image_hbox.pack_start(gtk.HBox())
        self.image_hbox.pack_start(self.image, False, False)
        self.image_hbox.pack_start(gtk.HBox())
        if self.camera != None:
            self.dialog.vbox.pack_start(self.image_hbox)
        self.dialog.vbox.pack_start(self.help_text, False, True)
        self.close_button = gtk.Button('Close')
        self.dialog.vbox.pack_start(self.close_button, False, True)
        self.close_button.connect('clicked', self.close_clicked)
        self.dialog.connect('response', self.dialog_response)


        self.image.add_events(gtk.gdk.BUTTON_PRESS_MASK)
        self.image.connect('button-press-event', self.image_clicked)
        self.dialog.show_all()

    def close_clicked(self, widget):
        self.close()

    def dialog_response(self, widget, response_id):
        self.close()

    def close(self):
        if self.camera:
            self.camera.stop()
            if self.camera.buffer:
                pixbuf = gtk.gdk.pixbuf_new_from_data(self.camera.buffer,
                    gtk.gdk.COLORSPACE_RGB, False, 8, self.camera.width,
                    self.camera.height, 3*self.camera.width)
                self.cb(pixbuf)
            else:
                self.cb(None)
        self.dialog.destroy()

    def image_clicked(self, widget, data=None):
        if self.camera:
            self.camera.take_photo()

