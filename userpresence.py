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
from plugins import Plugin, get_plugin_by_type
from proximateprotocol import PLUGIN_TYPE_COMMUNITY, PLUGIN_TYPE_NOTIFICATION, PLUGIN_TYPE_USER_PRESENCE
from userpresence_gui import User_Presence_GUI

community = None
notify = None

class Pattern:
    def __init__(self, dict):
        self.dict = dict

    def match(self, user):
        for (key, value) in self.dict.iteritems():
            if user.get(key).find(value) < 0:
                return False
        return True

    def __str__(self):
        return str(self.dict)

class User_Presence_Plugin(Plugin):
    def __init__(self):
        global community, notify

        self.register_plugin(PLUGIN_TYPE_USER_PRESENCE)
        community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        notify = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)
        self.patterns = []

    def user_appears(self, user):
        nick = user.get('nick')
        for p in self.patterns:
            if p.match(user):
                notify.notify_with_response('User %s appeared' % nick, self.response_handler, None)

    def user_changes(self, user, what=None):
        for p in self.patterns:
            if p.match(user):
                notify.notify_with_response('User %s appeared' % nick, self.response_handler, None)

    def response_handler(self, response, msg, ctx):
        return False

    def add_pattern(self, pdict):
        p = Pattern(pdict)
        self.patterns.append(p)

    def delete_pattern(self, pattern):
        self.patterns.remove(p)

    def get_patterns(self):
        return self.patterns

def init(options):
    if options.presence:
        User_Presence_Plugin()
