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

from proximateprotocol import PLUGIN_TYPE_SETTINGS
from plugins import get_plugin_by_type
from guiutils import GUI_Page
from utils import str_to_int

class Settings_GUI(GUI_Page):
    def __init__(self, gui):
        GUI_Page.__init__(self, 'Settings')

        self.settings = get_plugin_by_type(PLUGIN_TYPE_SETTINGS)
        self.main_gui = gui

        self.vbox = gtk.VBox(False, 5)

        for s in self.settings.settings:
            self.add_setting(s)

        self.settings.new_setting_cb.append(self.add_setting)

        self.initialize_menu()

        self.pack_start(self.vbox)
        self.show_all()
        self.main_gui.add_page(self)

    def add_setting(self, s):
        if s.descr == None:
            return
        if s.vtype == bool:
            widget = gtk.CheckButton(s.descr)
            widget.set_active(s.value)
            widget.connect('toggled', self.set_checkbox, s)
        elif s.vtype == str or s.vtype == int:
            widget = gtk.HBox()
            widget.pack_start(gtk.Label(s.descr + ':'), False)
            entry = gtk.Entry()
            entry.set_text(str(s.value))
            entry.connect('focus-out-event', self.entry_focus_out, s)
            widget.pack_start(entry)
        # TODO: other types
        self.vbox.pack_start(widget, False)
        self.vbox.show_all()

    def entry_focus_out(self, entry, event, s):
        value = entry.get_text()
        if s.vtype == int:
            value = str_to_int(value, None)
            if value == None:
                entry.set_text(str(s.value))
                return
        if value != s.value:
            if not s.set(value):
                entry.set_text(str(s.value))

    def set_checkbox(self, widget, s):
        s.set(widget.get_active())

    def initialize_menu(self):
        item = gtk.MenuItem('Edit settings')
        item.connect('activate', self.settings_clicked)
        self.main_gui.add_preferences_item(item)

    def settings_clicked(self, menu):
        self.main_gui.show_page(self)

def init_ui(main_gui):
    Settings_GUI(main_gui)
