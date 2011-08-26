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
""" Plugin that buzzes N900's vibrator when user marked as friend appears """

from dbus import SystemBus, SessionBus
from dbus.exceptions import DBusException
from dbus.mainloop.glib import DBusGMainLoop

from plugins import Plugin, get_plugin_by_type
from support import warning, debug
from proximateprotocol import PLUGIN_TYPE_VIBRA, \
    PLUGIN_TYPE_SEND_FILE, PLUGIN_TYPE_NOTIFICATION

class Vibra_Plugin(Plugin):

    def __init__(self):
        DBusGMainLoop(set_as_default=True)

        self.bus = SystemBus()
        self.sessionbus = SessionBus()
        try:
            self.mce = self.bus.get_object('com.nokia.mce', '/com/nokia/mce')
        except DBusException:
            warning('Nokia MCE not found. Vibra is disabled\n')
            return

        self.profiled = self.sessionbus.get_object('com.nokia.profiled', '/com/nokia/profiled')

        self.sessionbus.add_signal_receiver(self.profile_changed_handler, 'profile_changed',
                                            'com.nokia.profiled', 'com.nokia.profiled',
                                            '/com/nokia/profiled')

        profile = self.profiled.get_profile(dbus_interface='com.nokia.profiled')
        self.get_vibra_enabled(profile)

        self.register_plugin(PLUGIN_TYPE_VIBRA)

    def ready(self):
        self.notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)

        sendfile = get_plugin_by_type(PLUGIN_TYPE_SEND_FILE)
        sendfile.receive_cb.append(self.file_receive)

    def get_vibra_enabled(self, profile):
        self.enabled = self.profiled.get_value(profile, 'vibrating.alert.enabled', dbus_interface='com.nokia.profiled') == 'On'
        debug('Vibra enabled: %s\n' % self.enabled)

    def profile_changed_handler(self, foo, bar, profile, *args):
        self.get_vibra_enabled(profile)

    def vibrate(self):
        if self.enabled:
            self.mce.req_vibrator_pattern_activate('PatternChatAndEmail',
                dbus_interface='com.nokia.mce.request')

    def file_receive(self, cb, user, fname):
        self.vibrate()

    def user_appears(self, user):
        if user.get('friend'):
            self.vibrate()

def init(options):
    Vibra_Plugin()
