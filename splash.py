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
from pathname import ICON_DIR, get_dir
from os.path import join

class Splash:
    def __init__(self):
        self.initialized = False

    def show(self):
        self.splashwindow = gtk.Window()
        self.splashwindow.set_title("Proximate is starting...")
        self.splashwindow.set_position(gtk.WIN_POS_CENTER)
        self.splashimage = gtk.Image()
        self.splashimage.set_from_file(join(get_dir(ICON_DIR), "people_icon.png"))
        self.splashwindow.add(self.splashimage)
        self.splashwindow.show_all()
        self.initialized = True

        # For some reason this needs to be done twice,
        # for the window and for the image
        while gtk.events_pending():
            gtk.main_iteration()
        while gtk.events_pending():
            gtk.main_iteration()

    def hide(self):
        if self.initialized:
            self.splashwindow.destroy()

splash_screen = Splash()

def splash_show():
    splash_screen.show()

def splash_hide():
    splash_screen.hide()
