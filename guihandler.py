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
"""
Main window, root notebook, navigation history
"""
import gtk
import gobject
import pango
from os.path import join

from general_dialogs import Approve_Deny_Dialog_2
from pathname import ICON_DIR, get_dir
from plugins import get_plugin_by_type
from support import debug, normal_mode, set_debug_mode, warning, get_version, die
from proximateprotocol import PLUGIN_TYPE_COMMUNITY, PLUGIN_TYPE_NOTIFICATION, \
    PLUGIN_TYPE_SETTINGS
import proximatestate
from utils import pretty_line, str_to_int

have_hildon = True
try:
    import hildon
except ImportError:
    have_hildon = False

import splash

APP_NAME = 'Proximate'
STATUSBAR_ICON_SIZE = 64

MIN_WIDTH = gtk.gdk.screen_width()/2
MIN_HEIGHT = gtk.gdk.screen_height() * 36 / 100

class Proximate_GUI:
    """ Main GUI component for Proximate.

    This class implements all the main components of GUI and offers
    actions for GUI parts of other plugins. Also, guihandler initializes
    all plugin GUI's after initializing itself. """

    #images
    BACK_BUTTON1_IMG = '48px-Go-previous.png'

    def __init__(self):
        """Constructor for Proximate_GUI."""

        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        self.notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)

        settings = get_plugin_by_type(PLUGIN_TYPE_SETTINGS)

        self.width_setting = settings.register('gui.width', int, None, 0)
        self.height_setting = settings.register('gui.height', int, None, 0)

        self.page_history = []
        self.main_window = None

        self.initialize_menu()

        try:
            # This only seem to only exists on Maemo
            gtk.set_application_name(APP_NAME)
        except AttributeError:
            pass

        button = gtk.Button()
        button.get_settings().set_property('gtk-button-images', True)

        if have_hildon:
            self.initialize_hildon_program()
        else:
            self.initialize_gtk_program()

        self.main_loop = gobject.MainLoop()

        self.fullscreen_mode = False

        self.keybindings = []
        self.add_key_binding(None, gtk.keysyms.F6, self.key_pressed_F6)
        self.add_key_binding(gtk.gdk.CONTROL_MASK, gtk.keysyms.q, self.key_pressed_ctrl_q)

        self.popup_timeout_id = None
        self.event_clicked_at = None

        self.statusbar_timeout_id = None

        self.tbitems = {}

        # Signal Ids for connecting communities' userlists
        self.userlist_drag_data_get_signal_ids = {}
        self.userlists_button_press_signal_ids = {}

        # Initialize menu
        self.connect_default_menu_signals()

        self.notification.register_progress_update(self.handle_progress_update)

    def add_key_binding(self, mask, key, callback, ctx=None):
        self.keybindings.append((mask, key, callback, ctx))

    def key_pressed_F6(self, target, ctx):
        # if fullscreen key is pressed
        if self.fullscreen_mode:
            self.main_window.unfullscreen()
            debug('GUI: Fullscreen mode OFF\n')
        else:
            self.main_window.fullscreen()
            debug('GUI: Fullscreen mode ON\n')

    def key_pressed_ctrl_q(self, target, ctx):
        self.quit()

    def run(self):
        try:
            self.main()
        except KeyboardInterrupt:
            pass

    def main(self):
        """ Starts GObject's main loop. """
        splash.splash_hide()
        self.main_loop.run()

    def load_config(self):
        # make sure that dimensions are something sane
        window_width = max(300, self.width_setting.value)
        window_height = max(200, self.height_setting.value)
        # set size
        debug('Proximate GUI: Resizing main window to %ix%i\n' %(window_width, window_height))
        self.main_window.set_default_size(window_width, window_height)

    def quit(self):
        """ Quits GObject's main loop. """
        debug('GUI: Exiting application\n')
        self.main_loop.quit()

    def quit_clicked(self, widget, *args):
        self.main_window.destroy()

    def initialize_widgets(self):
        self.proximate_main_vbox = gtk.VBox()
        self.root_notebook = gtk.Notebook()
        self.root_notebook.set_show_tabs(False)
        self.root_notebook.set_show_border(False)

        # Status hbox: on the bottom of GUI
        self.status_hbox = gtk.HBox()
        self.back_button_eb = gtk.EventBox()
        self.main_progress_bar = gtk.ProgressBar()
        self.main_progress_bar.modify_font(pango.FontDescription('normal 20'))
        self.main_progress_bar.set_ellipsize(pango.ELLIPSIZE_END)
        self.status_icons_hbox = gtk.HBox()
        self.status_hbox.pack_start(self.back_button_eb, False, False)
        self.status_hbox.pack_start(self.main_progress_bar, True, True)
        self.status_hbox.pack_start(self.status_icons_hbox, False, True)

        # Add menubar at the top..
        self.proximate_main_vbox.pack_start(self.main_menu, False, False)

        # Put elements inside main_vbox
        self.proximate_main_vbox.pack_end(self.status_hbox, False, False)
        self.proximate_main_vbox.pack_end(self.root_notebook, True, True)

        button_img = gtk.Image()
        button_img.set_from_file(join(get_dir(ICON_DIR), self.BACK_BUTTON1_IMG))
        self.back_button_eb.add(button_img)
        self.back_button_eb.connect("button-press-event", self.back_button_cb)

        self.main_window.add(self.proximate_main_vbox)

    def handle_progress_update(self, indicators):
        """ Called when some progress indicator changes. This has the effect
            on animated progress on the status bar at the bottom. """

        if len(indicators) > 0:
            self.main_progress_bar.set_text(indicators[0].name + ': ' + indicators[0].msg)

            if self.statusbar_timeout_id == None:
                self.statusbar_timeout_id = gobject.timeout_add(100, self.statusbar_update_handler)
        else:
            self.main_progress_bar.set_text('')
            self.main_progress_bar.set_fraction(0.0)
            if self.statusbar_timeout_id != None:
                gobject.source_remove(self.statusbar_timeout_id)
            self.statusbar_timeout_id = None

    def statusbar_update_handler(self):
        self.main_progress_bar.pulse()
        return True

    def initialize_menu(self):
        self.version_menu_item = gtk.MenuItem("Version")

        self.plugins_menu_item = gtk.MenuItem("Plugins")
        self.plugins_menu = gtk.Menu()
        self.plugins_menu_item.set_submenu(self.plugins_menu)

        self.preferences_menu_item = gtk.MenuItem("Preferences")
        self.preferences_menu = gtk.Menu()
        self.preferences_menu_item.set_submenu(self.preferences_menu)
        self.quit_menu_item = gtk.MenuItem("Quit")

        for (name, function) in (('Debug mode', self.debug_mode_clicked),
                                 ('Normal mode', self.normal_mode_clicked),
                                ):
            item = gtk.MenuItem(name)
            item.connect('activate', function)
            self.add_preferences_item(item)

    def debug_mode_clicked(self, menu, data=None):
        set_debug_mode(True)
        self.notification.notify('Entering debug mode (AYEE!)')

    def normal_mode_clicked(self, menu, data=None):
        normal_mode()
        self.notification.notify('Leaving debug mode (fix it later..)')

    def initialize_hildon_program(self):
        """ Function creates hildon program and window from
        UI main window (proximate). Function also connects required events
        for using tablet's fullscreen button. """

        # Creates hildon Program
        self.program = hildon.Program()

        # Create the menu
        self.main_menu = gtk.Menu()
        self.main_menu.append(self.version_menu_item)
        self.main_menu.append(self.plugins_menu_item)
        self.main_menu.append(self.preferences_menu_item)
        self.main_menu.append(self.quit_menu_item)
        self.program.set_common_menu(self.main_menu)

        self.main_progress_bar = gtk.ProgressBar()
        self.main_progress_bar.modify_font(pango.FontDescription('normal 20'))
        self.main_progress_bar.set_ellipsize(pango.ELLIPSIZE_END)

        self.tb = gtk.Toolbar()
        item = gtk.ToolItem()
        item.add(self.main_progress_bar)
        item.set_expand(True)
        self.tb.insert(item, -1)
        self.tb.show()
        self.program.set_common_toolbar(self.tb)

        # fix maemos treeview appearance inside a pannablearea
        gtk.rc_parse_string('''style "fremantle-touchlist" {
            GtkTreeView::row-height = -1 }''')

        # fullscreen
        #self.main_window.connect("window-state-event", self.on_window_state_change)

    def window_configure(self, window, event):
        self.width_setting.set(event.width)
        self.height_setting.set(event.height)

    def initialize_gtk_program(self):
        self.main_window = gtk.Window()
        self.main_window.set_title(APP_NAME)
        self.main_window.connect('configure-event', self.window_configure)
        self.load_config() # this must be done here
        self.main_window.set_icon_from_file(join(get_dir(ICON_DIR), "proximate_task_icon.png"))

        # Create the menubar
        self.main_menu = gtk.MenuBar()
        self.app_menu_item = gtk.MenuItem("Application")
        self.app_menu = gtk.Menu()
        self.app_menu_item.set_submenu(self.app_menu)
        self.main_menu.append(self.app_menu_item)
        self.main_menu.append(self.preferences_menu_item)
        self.app_menu.append(self.version_menu_item)
        self.main_menu.append(self.plugins_menu_item)
        self.app_menu.append(self.quit_menu_item)

        self.initialize_widgets()

        self.main_window.connect("delete-event", self.close_proximate)
        self.main_window.connect("key-press-event", self.on_key_press)
        self.main_window.show_all()

    def on_key_press(self, widget, event, *args):
        for (mask, keyval, callback, ctx) in self.keybindings:
            if mask != None and (event.state & mask) == 0:
                continue
            if keyval == event.keyval:
                target = self.community.get_default_community()
                callback(target, ctx)
                return True
        return False

    def on_window_state_change(self, widget, event, *args):
        if event.new_window_state & gtk.gdk.WINDOW_STATE_FULLSCREEN:
            self.fullscreen_mode = True
        else:
            self.fullscreen_mode = False

    def add_menu(self, name, menu):
        new_plugin_menu = gtk.MenuItem(name)
        new_plugin_menu.set_submenu(menu)

        self.plugins_menu.append(new_plugin_menu)
        new_plugin_menu.show_all()

    def add_preferences_item(self, menuitem):
        self.preferences_menu.append(menuitem)
        menuitem.show_all()

    def add_statusbar_icon(self, icon, tooltip, callback):
        """ Adds new icon to statusbar. By clicking the icon,
        the given callback is called."""

        eventbox = gtk.EventBox()
        try: # Maemos PyGTK 2.12 doesn't seem to have
             #set_tooltip_text() though it should
            eventbox.set_tooltip_text(tooltip)
        except:
            pass
        statusbar_image = gtk.Image()
        statusbar_image.set_from_pixbuf(icon)
        eventbox.add(statusbar_image)
        if have_hildon:
            item = gtk.ToolItem()
            item.add(eventbox)
            self.tb.insert(item, -1)
            self.tb.show_all()
            self.tbitems[eventbox] = item
        else:
            self.status_icons_hbox.pack_end(eventbox)
            self.status_icons_hbox.show_all()
        if callback != None:
            eventbox.connect("button-press-event", self.status_icon_clicked, callback)
        return eventbox

    def remove_statusbar_icon(self, widget):
        """ Removes icon from statusbar. """

        if have_hildon:
            # hackhackhack
            self.tb.remove(self.tbitems[widget])
            self.tbitems.pop(widget)
        else:
            self.status_icons_hbox.remove(widget)

    def display_version(self, widget):
        headline = 'Proximate %s' % get_version()
        msg = headline + """

Department of Computer Systems (2008-2010),
Tampere University of Technology.

Authors:

Timo Heinonen <timo.heinonen@tut.fi>
Tero Huttunen <tero.huttunen@tut.fi>
Janne Kulmala <janne.t.kulmala@tut.fi>
Antti Laine <antti.a.laine@tut.fi>
Jussi Nieminen <jussi.v.nieminen@tut.fi>
Heikki Orsila <heikki.orsila@tut.fi>

More information about copyrights and credits in
/usr/share/doc/proximate/AUTHORS
"""
        self.notification.ok_dialog(headline, msg)

    def status_icon_clicked(self, widget, event, callback):
        callback()

    def connect_default_menu_signals(self):
        self.version_menu_item.connect("activate", self.display_version)
        self.quit_menu_item.connect("activate", self.menu_close_proximate)

    def menu_close_proximate(self, widget):
        self.close_proximate(None)

    def close_proximate(self, widget, data=None):
        dlg = Approve_Deny_Dialog_2(widget, 'Close Proximate?', 'Do you really want to close Proximate?', modal=True)
        if dlg.run():
            self.quit()
        return True

    def back_button_cb(self, widget, event):
        self.go_back_one_page()

    def go_back_one_page(self):
        """ Go to previous page in root notebook navigation history. Can be
            called from plugins, for ex. when plugin needs to hide a page."""

        if len(self.page_history) > 0:
            self.go_back_page(self.page_history[-1])

    def delete_window(self, widget, event, page):
        self.go_back_page(page)
        return True

    def go_back_page(self, page):
        if not page.is_visible:
            return
        if not page.back_action():
            # default action: just hide the page
            self.hide_page(page)

    def add_page(self, page):
        if have_hildon:
            page.hwindow.connect('delete_event', self.delete_window, page)
            page.hwindow.connect("key-press-event", self.on_key_press)
            self.program.add_window(page.hwindow)
        else:
            self.root_notebook.append_page(page)

    def remove_page(self, page):
        if page.is_visible:
            self.hide_page(page)
        if have_hildon:
            self.program.remove_window(page.hwindow)
        else:
            self.root_notebook.remove(page)

    def has_focus(self):
        """ Returns true if Proximate window has focus """
        if have_hildon:
            return self.page_history[-1].hwindow.get_property('has-toplevel-focus')
        else:
            return self.main_window.get_property('has-toplevel-focus')

    def show_page(self, page):
        """ Display the given GUI page to the user """

        if have_hildon:
            if page.is_visible:
                page.hwindow.hide()
            page.hwindow.show()
            # Use first shown page as the main window
            if self.main_window == None:
                self.main_window = page.hwindow
        else:
            self.set_visible_page(page)

        if page.is_visible:
           self.page_history.remove(page)

        self.page_history.append(page)
        page.is_visible = True

    def hide_page(self, page):
        """ Hide the given GUI page by removing it from the navigation history """

        assert(page.is_visible)
        if have_hildon:
            page.hwindow.hide()
        else:
            if page == self.page_history[-1]:
                # currently visible page, go to the previous one
                self.set_visible_page(self.page_history[-2])
        self.page_history.remove(page)
        page.is_visible = False

    def get_current_page(self):
        return self.page_history[-1]

    def set_visible_page(self, page):
        """ For internal use """
        self.root_notebook.set_current_page(self.root_notebook.page_num(page))
        title = '%s - %s' % (APP_NAME, page.get_page_title())
        self.main_window.set_title(title)

    def get_main_window(self):
        return self.main_window

    def pretty_line(self, msg):
        n = 80
        if have_hildon:
            n = 60
        return pretty_line(msg, n)

    def set_user_double_clicking(self, doubleclick):
        self.user_double_clicking = doubleclick
        return False # timeout shouldn't call this again

def run_gui():
    """ Start Graphical User Interface """

    main_gui = Proximate_GUI()

    for modulename in ['community_gui', 'messaging_gui',
                       'notification_gui', 'filesharing_gui',
                       'messageboard_gui', 'filetransfergui',
                       'radar', 'keymanagement_gui', 'settings_gui']:
        module = __import__(modulename)
        try:
            module.init_ui(main_gui)
        except TypeError:
            die('GUI module %s init() called with invalid arguments\n' %(modulename))

    proximatestate.load_external_plugins(ui=main_gui)

    main_gui.run()
