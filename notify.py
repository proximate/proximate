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
Notification Plugin is a common interface for
showing messages to user.

Guidelines for showing notifications:
    - Unimportant messages that inform user of events
      and are just nice to know: notify() with low priority
    - Unimportant messages that user should notice:
      notify() with high priority
    - Important messages that user must notice, such as error messages:
      ok_dialog()
"""

from gobject import source_remove, timeout_add_seconds

from plugins import Plugin, get_plugin_by_type
from support import info
from proximateprotocol import PLUGIN_TYPE_NOTIFICATION, PLUGIN_TYPE_VIBRA, \
    PLUGIN_TYPE_SETTINGS

progress_callback = None
progress_indicators = []

class Progress_Indicator:
    def __init__(self, name):
        self.msg = None
        self.name = name
        self.cnt = 0
        self.timeouttag = None

    def set_status(self, msg, timeout=None):
        """ progress() is used to report on-going operations.

            If msg != None, report progress. Otherwise stop it.

            Status is cancelled withint timeout seconds if timeout != None.
            Calling set_status() or clear_status() before the timeout
            is allowed.

            Returns a number for pending status that can be used
            to clear the status by calling self.clear_status(number).
        """

        self.msg = msg
        if progress_callback != None:
            indicators = filter(lambda p: p.msg != None, progress_indicators)
            progress_callback(indicators)
        else:
            info('Progress indicator: %s\n' % msg)

        if self.timeouttag != None:
            source_remove(self.timeouttag)
            self.timeouttag = None

        if msg == None:
            return None

        self.cnt += 1
        if timeout != None:
            self.timeouttag = timeout_add_seconds(timeout, self.clear_status, self.cnt)
        return self.cnt

    def clear_status(self, pending):
        if pending == self.cnt:
            self.set_status(None)
        return False

class Notification_Plugin(Plugin):
    
    DEFAULT_TIMEOUT = 3000
    RESPONSE_ACTIVATED = 0
    RESPONSE_DELETED = 1

    def __init__(self):
        self.register_plugin(PLUGIN_TYPE_NOTIFICATION)
        self.ui = None

    def ready(self):
        self.vibra = get_plugin_by_type(PLUGIN_TYPE_VIBRA)

        settings = get_plugin_by_type(PLUGIN_TYPE_SETTINGS)
        self.vibra_setting = settings.register('vibra.notify', bool, 'Vibrate on notifications', default=False)

    def register_ui(self, ui):
        self.ui = ui

    def notify(self, msg, highpri=False, delay=None):
        if highpri:
            info('IMPORTANT: ' + msg + '\n')
        else:
            info(msg + '\n')
        if self.ui != None:
            self.ui.notification_show(msg, highpri, delay, None)

    def user_notify(self, user, msg, highpri=False, delay=None):
        if highpri:
            info('IMPORTANT: %s %s\n' % (user.tag(), msg))
        else:
            info('%s %s\n' % (user.tag(), msg))
        if self.ui != None:
            self.ui.notification_show('%s %s' % (user.tag(), msg), highpri, delay, user)

    def get_progress_indicator(self, name):
        """ get_progress_indicator() returns a Progress_Indicator() object
        that can be used to signal on-going operations on the bottom
        statusbar (or elsewhere). """

        p = Progress_Indicator(name)
        progress_indicators.append(p)
        return p

    def register_progress_update(self, callback):
        """ This is only called by the main GUI system, not by plugins. """
        global progress_callback
        progress_callback = callback

    def notify_with_response(self, msg, response_handler=None, ctx=None):
        """ callback: response_handler(response, msg, ctx)
              Returns True if message response was handled.
              Response is either RESPONSE_ACTIVATED or
              RESPONSE_DELETED.
        """
        if self.ui != None:
            visible = self.ui.notification_with_response_show(msg, response_handler, ctx)
            if not visible and self.vibra != None and self.vibra_setting.value == True:
                self.vibra.vibrate()

    def ok_dialog(self, headline, msg, destroy_cb=None, parent=None, modal=False):
        info('OK dialog: %s: %s\n' %(headline, msg))
        if self.ui != None:
            self.ui.ok_dialog(headline, msg, destroy_cb, parent, modal)

def init(options):
    Notification_Plugin()
