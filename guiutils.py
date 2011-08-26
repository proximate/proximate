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
import gobject
import gtk
import os
have_hildon = True
have_mokoui = True
try:
    import hildon
except ImportError:
    have_hildon = False
try:
    import mokoui
except ImportError:
    have_mokoui = False

from ossupport import xremove

class GUI_Page(gtk.HBox):
    def __init__(self, title):
        gtk.HBox.__init__(self)

        self.page_title = title
        self.page_subtitle = None
        self.is_visible = False

        if have_hildon:
            self.hwindow = hildon.StackableWindow()
            self.update_page_title()
            self.hwindow.add(self)

    def back_action(self):
        return False

    def get_page_title(self):
        title = self.page_title
        if self.page_subtitle != None:
            title += ' - %s' % self.page_subtitle
        return title

    def set_page_title(self, title, sub=False):
        if sub:
            self.page_subtitle = title
        else:
            self.page_title = title
        self.update_page_title()

    def update_page_title(self):
        if have_hildon:
            self.hwindow.set_title(self.get_page_title())

    def get_community(self):
        return None

class Action_List:
    def __init__(self):
        self.list = gtk.VBox()
        self.action_view = new_scrollarea()
        self.action_view.set_size_request(220, -1)
        self.action_view.add_with_viewport(self.list)

    def add_button(self, icon, name, callback, ctx = None):
        button = new_button(name)
        button.set_image(gtk.image_new_from_pixbuf(icon))
        button.connect('clicked', self.clicked, callback, ctx)
        self.list.pack_start(button, False, True)
        button.show()

    def clicked(self, widget, callback, ctx):
        callback(ctx)

    def get_widget(self):
        return self.action_view

def new_filechooser(parent, dtype):
    dlg = None
    if have_mokoui and have_hildon:
        # mokoui and hildon available, should be Maemo 4
        dlg = hildon.FileChooserDialog(parent, dtype)
    elif have_hildon:
        # only hildon available, should be Maemo 5
        dlg = gobject.new(hildon.FileChooserDialog, action=dtype)
    else:
        dlg = gtk.FileChooserDialog('Choose a File', parent, dtype,
                                    (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                     gtk.STOCK_OPEN, gtk.RESPONSE_OK))
    return dlg

def new_scrollarea():
    """ Creates a scrollable area depending on the platform.
        All the widget types have add() and add_with_viewport()
    """
    widget = None
    if have_mokoui:
        # use mokoui on Maemo 4
        widget = mokoui.FingerScroll()
        widget.set_property('mode', 0)
    elif have_hildon:
        # use hildon on Maemo 5
        widget = hildon.PannableArea()
    else:
        widget = gtk.ScrolledWindow()
        widget.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
    return widget

def new_textview():
    if have_hildon:
        view = hildon.TextView()
    else:
        view = gtk.TextView()
    return view

def new_button(label):
    if have_hildon:
        button = hildon.Button(
            gtk.HILDON_SIZE_AUTO_WIDTH | gtk.HILDON_SIZE_FINGER_HEIGHT,
            hildon.BUTTON_ARRANGEMENT_HORIZONTAL)
        button.set_title(label)
    else:
        button = gtk.Button(label)
    return button

def new_entry(placeholder=None):
    if have_hildon:
        entry = hildon.Entry(gtk.HILDON_SIZE_FINGER_HEIGHT)
        if placeholder:
            entry.set_placeholder(placeholder)
    else:
        entry = gtk.Entry()
    return entry

def scale_image(original, larger_dimension):
    """ Scales the original GDK Pixbuf image to fit larger_dimension
        and saves the resulting image as a png to file fname """
    factor = min(float(larger_dimension) / original.get_width(),
        float(larger_dimension) / original.get_height(), 1.0)
    w = int(original.get_width() * factor)
    h = int(original.get_height() * factor)
    new = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, original.get_has_alpha(),
        original.get_bits_per_sample(), w, h)
    new.fill(0x000000) # clear the buffer filling it with transparency
    original.composite(new, 0, 0, w, h, 0, 0, factor, factor,
        gtk.gdk.INTERP_BILINEAR, 255)
    return new

def compress_jpeg(pixbuf, fname, maxsize):
    quality = 95
    while quality > 0:
       pixbuf.save(fname, 'jpeg', {'quality': str(quality)})
       if os.path.getsize(fname) <= maxsize:
           return True
       quality -= 10
    xremove(fname)
    return False

def center_image(original, new_width, new_height):
    """ Creates a new transparent image with size new_width x new_height
        and draws the smaller original image to the center of it. """
    new = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True,
        original.get_bits_per_sample(), new_width, new_height)
    new.fill(0x000000)
    offset_x = (new_width / 2) - (original.get_width() / 2)
    offset_y = (new_height / 2) - (original.get_height() / 2)
    original.copy_area(0, 0, original.get_width(), original.get_height(),
        new, offset_x, offset_y)
    return new

def add_icon_to_image(img, icon, index):
    """ Adds a small status icon to the bottom of the image.
       Index tells the x-position for the icon: width*index.
       Status icons should be 32 pixels wide """

    # area for the composite
    r1 = gtk.gdk.Rectangle()
    r1.x = icon.get_width() * index
    r1.y = img.get_height() - icon.get_height()
    r1.width  = icon.get_width()
    r1.height = icon.get_height()

    r2 = gtk.gdk.Rectangle()
    r2.x = 0
    r2.y = 0
    r2.width  = img.get_width()
    r2.height = img.get_height()

    dest = r1.intersect(r2)

    icon.composite(img, dest.x, dest.y, dest.width, dest.height,
        r1.x, r1.y, 1.0, 1.0, gtk.gdk.INTERP_BILINEAR, 255)

def pango_escape(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

