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
from plugins import get_plugin_by_type
from proximateprotocol import PLUGIN_TYPE_COMMUNITY, PLUGIN_TYPE_USER_PRESENCE
from guiutils import new_scrollarea
import gtk

userpresence = None
community = None

class User_Presence_GUI:
    def __init__(self, main_gui):
        global userpresence

        userpresence = get_plugin_by_type(PLUGIN_TYPE_USER_PRESENCE)
        self.main_gui = main_gui
        self.menu = gtk.Menu()
        menuitem = gtk.MenuItem('Edit user watches')
        menuitem.connect('activate', self.add_user_watch_cb)
        self.menu.append(menuitem)
        self.main_gui.add_menu('Presence', self.menu)

    def add_user_watch_cb(self, widget, data=None):
        dlg = Watch_Editor(self.main_gui)
        response = dlg.run()
        dlg.destroy()

class Watch_Editor(gtk.Dialog):
    def __init__(self, main_gui):
        self.main_gui = main_gui
        self.main_window = main_gui.get_main_window()
        gtk.Dialog.__init__(self, 'Watch editor', self.main_window,
                            gtk.DIALOG_DESTROY_WITH_PARENT | gtk.DIALOG_MODAL,
                            (gtk.STOCK_CLOSE, gtk.RESPONSE_CLOSE))

        action_area = self.action_area
        content_area = self.vbox

        watch_area = new_scrollarea()
        self.watch_view = gtk.TreeView()
        
        cr1 = gtk.CellRendererText()
        col1 = gtk.TreeViewColumn('Watch')
        col1.pack_start(cr1, True)

        self.watch_view.append_column(col1)
        col1.add_attribute(cr1, 'text', 0)


        watch_area.add(self.watch_view)

        content_area.pack_start(watch_area)


        add_button = gtk.Button(stock=gtk.STOCK_ADD)
        delete_button = gtk.Button(stock=gtk.STOCK_DELETE)
        edit_button = gtk.Button(stock=gtk.STOCK_EDIT)

        add_button.connect('clicked', self.add_clicked_cb)
        delete_button.connect('clicked', self.delete_clicked_cb)
        edit_button.connect('clicked', self.edit_clicked_cb)

        action_area.pack_start(add_button)
        action_area.pack_start(delete_button)
        action_area.pack_start(edit_button)


        self.show_all()

    def add_clicked_cb(self, widget):
        pdict = {'nick': 'Julia'}
        userpresence.add_pattern(pdict)
        self.update_pattern_list()

    def delete_clicked_cb(self, widget):
        print 'Delete button clicked'
        selection = self.watch_view.get_selection()

        self.update_pattern_list()

    def edit_clicked_cb(self, widget):
        print 'Edit button clicked'
        self.update_pattern_list()

    def update_pattern_list(self):
        store = gtk.ListStore(str, object)
        for p in userpresence.get_patterns():
            store.append(['%s' % str(p), p])

        self.watch_view.set_model(store)
