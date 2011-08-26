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
from gobject import timeout_add, source_remove
from os.path import join

from guiutils import pango_escape, GUI_Page
from support import info, debug, warning
from community import get_myself, get_user
from pathname import get_dir, ICON_DIR
from plugins import get_plugin_by_type
from proximateprotocol import PLUGIN_TYPE_KEY_MANAGEMENT, PLUGIN_TYPE_COMMUNITY, \
    PLUGIN_TYPE_NOTIFICATION
from general_dialogs import Approve_Deny_Dialog

class Key_Management_GUI:
    """ User interface for exchanging and managing encryption keys """

    def __init__(self, gui):
        self.keymanagement = get_plugin_by_type(PLUGIN_TYPE_KEY_MANAGEMENT)
        self.notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)

        self.main_gui = gui
        self.dialog = gtk.Dialog('Key Management', gui.main_window,
            gtk.DIALOG_DESTROY_WITH_PARENT | gtk.DIALOG_MODAL,
            (gtk.STOCK_APPLY, gtk.RESPONSE_APPLY,
             gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL))
        self.key_label = gtk.Label('Key ID: ')
        self.dialog.vbox.pack_start(self.key_label, False, True)
        self.gen_button = gtk.Button('Regenerate keys')
        self.dialog.vbox.pack_start(self.gen_button, False, True)
        self.close_button = gtk.Button('Close')

        self.gen_button.connect('clicked', self.generate_keys)

        self.generator = None
        self.generating_keys = False

    def run(self):
        key_fname = get_myself().get('key_fname')
        if key_fname != '':
            keyid = key_fname.split('/')[-1].split('_')[1][:8]
            if keyid != '':
                self.key_label.set_label(keyid)

        self.toggle_apply(False)
        self.dialog.show_all()
        response = self.dialog.run()
        if response == gtk.RESPONSE_APPLY:
            if self.generating_keys:
                return
            self.keymanagement.save_key(get_myself(),
                priv=self.priv, pub=self.pub)
        else:
            self.generating_keys = False
            if self.generator:
                self.generator.cancel()
        self.main_gui.main_progress_bar.set_fraction(0.0)
        self.main_gui.main_progress_bar.set_text("")
        self.dialog.hide()
    
    def toggle_apply(self, state=None):
        if state == None: 
            state = not self.dialog.action_area.get_children()[1].get_property(
                'sensitive')
        self.dialog.action_area.get_children()[1].set_property('sensitive', state)
    
    def generate_keys(self, widget, data = None):
        self.generating_keys = True
        self.generator = self.keymanagement.gen_key_pair(2048, self.generate_keys_cb)
        self.keymanagement.progress_update('Generating permanent key, size 2048 bits')

    def generate_keys_cb(self, priv, pub):
        self.keymanagement.progress_update(None)
        if (priv and pub):
            self.notification.notify('Generated permanent key')
            keyid = self.keymanagement.key_hash(priv, pub)[:8]
            self.key_label.set_label(keyid)
            (self.priv, self.pub) = (priv, pub)
        else:
            self.notification.notify('Could not generate permanent key')
        self.generating_keys = False
        self.generator = None
        self.toggle_apply(True)

    def generate_perm_key_cb(self, ready):
        if ready:
            self.main_gui.main_progress_bar.set_text('')
        else:
            self.main_gui.main_progress_bar.set_text('No permanent key, generating...')

class Key_Exchange_GUI(GUI_Page):
    def __init__(self, gui):
        GUI_Page.__init__(self, 'Key exchange')

        self.keymanagement = get_plugin_by_type(PLUGIN_TYPE_KEY_MANAGEMENT)
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        self.notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)
        self.main_gui = gui
        self.user = None
        self.entered_key = ''
        self.request_dialog = None

        self.main_vbox = gtk.VBox()
        self.notebook = gtk.Notebook()
        self.notebook.set_show_tabs(False)
        self.main_vbox.pack_start(self.notebook)

        # notebook pages for differents stages of key exchange
        lock_image = gtk.image_new_from_file(join(get_dir(ICON_DIR),
            'Padlock.png'))
        # page 1: show messages
        page1 = gtk.VBox()
        self.messagelabel = gtk.Label()
        page1.pack_start(self.messagelabel)
        self.notebook.append_page(page1)
        # page 2: show generated symmetric key
        page2 = gtk.VBox()
        self.show_key_header = gtk.Label()
        page2.pack_start(self.show_key_header, False, True, 10)
        self.keylabel = gtk.Label()
        page2.pack_start(self.keylabel)
        key_show_eventbox = gtk.EventBox()
        key_show_eventbox.modify_bg(gtk.STATE_NORMAL,
            key_show_eventbox.get_colormap().alloc_color('red'))
        key_show_eventbox.add(page2)
        self.notebook.append_page(key_show_eventbox)
        # page 3: ask for symmetric key
        page3 = gtk.VBox()
        self.key_entry_header = gtk.Label()
        page3.pack_start(self.key_entry_header, False, True, 10)
        page3_hbox = gtk.HBox()
        page3.pack_start(page3_hbox)
        self.keyentry = gtk.Label()
        page3_hbox.pack_start(self.keyentry)
        page3_hbox.pack_start(lock_image, False, False)
        self.key_eventbox = gtk.EventBox()
        self.key_eventbox.set_events(gtk.gdk.KEY_PRESS_MASK)
        self.key_eventbox.set_flags(gtk.HAS_FOCUS | gtk.CAN_FOCUS)
        self.key_eventbox.modify_bg(gtk.STATE_NORMAL,
            self.key_eventbox.get_colormap().alloc_color('red'))
        self.key_eventbox.add(page3)
        self.notebook.append_page(self.key_eventbox)

        self.key_eventbox.connect('button-press-event', self.save_temp_key_clicked)
        self.key_eventbox.connect('key-press-event', self.key_entry_modify)

        self.pack_start(self.main_vbox)
        self.show_all()
        self.main_gui.add_page(self)

        self.keymanagement.register_ui(self)

    def run(self, user):
        if self.user:
            return
        self.user = user

        debug('Opening GUI to exchange keys with %s\n' %(user.get('nick')))
        if not self.keymanagement.community.get_myself().get("key_fname"):
            # we do not have a permanent key to exhange
            self.notification.ok_dialog('Key Management', 'You do not have a key to exchange.')
            return

        self.keymanagement.send_exchange_request(user)
        self.notification.notify('Key Management: Sending request to exchange keys with %s...' %(user.get('nick')))

    def back_action(self):
        if self.user:
            self.keymanagement.send_cancel(self.user)
            self.user = None
        return True

    def save_temp_key_clicked(self, widget, event, data=None):
        if len(self.entered_key) == self.keymanagement.passphraselen:
            self.keymanagement.save_symmetric_key(self.entered_key, self.user)
            self.entered_key = ''

    def key_entry_modify(self, widget, event, data=None):
        if event.keyval in range(gtk.keysyms.A, gtk.keysyms.Z + 1) + \
            range(gtk.keysyms.a, gtk.keysyms.z + 1) + \
            range(gtk.keysyms._0, gtk.keysyms._9 + 1):
                if len(self.entered_key) == self.keymanagement.passphraselen:
                    return
                else:
                    self.entered_key = self.entered_key + \
                        chr(gtk.gdk.keyval_to_unicode(event.keyval))
        elif event.keyval == gtk.keysyms.BackSpace:
            if len(self.entered_key) > 0:
                self.entered_key = self.entered_key[:-1]
        # N810's keyboard return has keycode 65421
        elif event.keyval in (gtk.keysyms.Return, 65421):
            if self.generating_temp:
                return
            self.save_temp_key_clicked(widget, event)
            return
        else:
            return

        self.set_keyentry_text()

    def set_keyentry_text(self):
        show_text = self.entered_key + (' <u> </u>' *
            (self.keymanagement.passphraselen - len(self.entered_key)))
        self.keyentry.set_markup('<span foreground="white" size="62000">%s</span>'
            %(show_text))
 
    def open_gui(self):
        """ This is called when:
            1. the user requests a key exchange
            2. the other user accepts the key exchange """
        self.main_gui.show_page(self)
        nick = pango_escape(self.user.get('nick'))
        self.show_key_header.set_markup(
            '<span foreground="white" size="xx-large">Show this secret to <b>%s</b></span>' %(nick))
        self.key_entry_header.set_markup(
            '<span foreground="white" size="xx-large">Enter secret from <b>%s</b></span>' %(nick))

    def close_gui(self):
        if not self.is_visible:
            return
        debug("keymanagement: Closing GUI\n")
        self.user = None
        if self.request_dialog:
            self.request_dialog.base.destroy()
        self.keymanagement.progress_update(None)
        self.main_gui.hide_page(self)

    def plugin_to_gui(self, user, request, isinitiator):
        nick = user.get('nick')
        if request == self.keymanagement.KM_REQUEST_KEY:
            self.user = user
            if not self.keymanagement.community.get_myself().get("key_fname"):
                # we do not have a permanent key to exhange
                self.request_dialog = Approve_Deny_Dialog(
                    self.main_gui.get_main_window(),
                    'Key Management',
                    '%s requests to exchange keys,\nbut you don\'t have a key.' %(nick),
                    self.dialog_response_request, user)
                self.request_dialog.base.action_area.get_children()[0].set_property(
                    "sensitive", False)
            else:
                self.request_dialog = Approve_Deny_Dialog(
                    self.main_gui.get_main_window(),
                    'Key Management',
                    '%s requests to exchange keys.\nAccept?' %(nick),
                    self.dialog_response_request, user)
        elif request == self.keymanagement.KM_REQUEST_ACK:
            self.open_gui()
            self.notebook.set_current_page(0)
            self.messagelabel.set_text('Waiting for an answer...')
            debug('Key management: showing page 1\n')
        elif request == self.keymanagement.KM_REQUEST_OK:
            timeout = timeout_add(100, self.wait_for_temp_key)
        elif request == self.keymanagement.KM_REQUEST_DENIED:
            self.notification.ok_dialog('Key Management', '%s denied your request to exchange keys.' %(nick))
            self.close_gui()
        elif request == self.keymanagement.KM_REQUEST_ANSWER_ACK:
            self.open_gui()
            self.notebook.set_current_page(2)
            self.key_eventbox.grab_focus()
            self.entered_key = ''
            self.set_keyentry_text()
            debug('Key management: showing page 3\n')
        elif request == self.keymanagement.KM_TEMP_KEY_ACK:
            self.messagelabel.set_text('Sending keys...')
            self.notebook.set_current_page(0)
        elif request == self.keymanagement.KM_TEMP_KEY1:
            self.messagelabel.set_text('Sending keys...')
            self.notebook.set_current_page(0)
        elif request == self.keymanagement.KM_FINISHED:
            self.notification.ok_dialog('Key Management', 'Successful key exchange!')
            self.close_gui()
        elif request == self.keymanagement.KM_CANCEL:
            self.notification.ok_dialog('Key Management', 'Key exchange canceled')
            self.close_gui()
        elif request == self.keymanagement.KM_ERROR:
            s = 'Error during key exchange!'
            if not isinitiator:
                s += '\nYou may possibly have written an incorrect code.'
            self.notification.ok_dialog('Key Management', s)
            self.close_gui()
        elif request == self.keymanagement.KM_REQUEST_NACK:
            self.notification.ok_dialog('Key Management', '%s is busy' %(nick))

    def dialog_response_request(self, response, user):
        self.request_dialog = None
        self.keymanagement.send_request_answer(response, user)

    def generating_temp_key(self):
        self.generating_temp = True
        self.keymanagement.progress_update('Generating temporary key')

    def generated_temp_key(self):
        self.generating_temp = False
        self.keymanagement.progress_update(None)

    def wait_for_temp_key(self):
        if not self.generating_temp:
            self.keylabel.set_markup('<span foreground="white" size="62000">%s</span>'
                %(self.keymanagement.temp_passphrase))
            self.notebook.set_current_page(1)
            debug('Key management: showing page 2\n')
            return False
        else:
            return True

def init_ui(main_gui):
    Key_Exchange_GUI(main_gui)
