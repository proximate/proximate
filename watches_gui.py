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
from os.path import join

from general_dialogs import Input_Dialog
from guiutils import GUI_Page, new_button, Action_List
from pathname import ICON_DIR, get_dir

class Watches_GUI:

    # list store columns
    COL_ICON = 0
    COL_NAME = 1
    COL_TARGET = 2

    def __init__(self, main_gui, getstatecb, modifycb):
        self.main_gui = main_gui

        self.modifycb = modifycb
        self.getstatecb = getstatecb

        self.guistate = 0

        self.page = GUI_Page('Watches')

        # self.watch_list stores columns: possible picture, keyword, target
        self.watch_list = gtk.ListStore(gtk.gdk.Pixbuf, str, str)
        self.update()

        self.watch_view = gtk.TreeView(self.watch_list)
        self.pic_cell = gtk.CellRendererPixbuf()
        self.name_cell = gtk.CellRendererText()
        self.target_cell = gtk.CellRendererText()
        self.pic_column = self.watch_view.insert_column_with_attributes(
            self.COL_ICON, '', self.pic_cell, pixbuf=self.COL_ICON)
        self.name_column = self.watch_view.insert_column_with_attributes(
            self.COL_NAME, '', self.name_cell, text=self.COL_NAME)
        self.target_column = self.watch_view.insert_column_with_attributes(
            self.COL_TARGET, '', self.target_cell, text=self.COL_TARGET)
        self.page.pack_start(self.watch_view, True, True)

        add_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), "64px-add_content_icon.png"))
        remove_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), "64px-remove_content_icon.png"))

        action_buttons = [(add_icon, 'Add', self.add_clicked),
                          (remove_icon, 'Remove', self.remove_clicked)
                         ]

        self.actions = Action_List()

        for action in action_buttons:
            (icon, text, cb) = action
            self.actions.add_button(icon, text, cb)

        self.page.pack_start(self.actions.get_widget(), False, True)

        self.main_gui.add_page(self.page)

    def show(self):
        self.page.show_all()
        self.main_gui.show_page(self.page)

    def add_clicked(self, widget):
        if self.guistate != 0:
            return
        self.guistate = 1
        Input_Dialog(self.main_gui.main_window, 'Add watch', 'Please give a keyword:', self.watch_added)

    def remove_clicked(self, widget):
        if self.guistate != 0:
            return
        selection = self.watch_view.get_selection()
        if selection == None:
            return
        model, selected = selection.get_selected()
        if selected != None:
            keyword = model[selected][1]
            self.modifycb(False, keyword)
        self.update()

    def update(self):
        self.watch_list.clear()
        for keyword in self.getstatecb():
            self.watch_list.append([None, keyword, ''])

    def watch_added(self, keyword, ctx=None):
        self.guistate = 0
        if keyword:
            self.modifycb(True, keyword)
        self.update()
