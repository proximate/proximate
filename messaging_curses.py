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
from gobject import timeout_add
import curses
from user import User
from communitymeta import Community
from messaging import user_from_addr, decode_addr

from cursesui import Curses_Page
from proximateprotocol import PLUGIN_TYPE_MESSAGING, PLUGIN_TYPE_COMMUNITY
from plugins import get_plugin_by_type

class Messaging_GUI(Curses_Page):
    def __init__(self, ui):
        Curses_Page.__init__(self, 'Messaging')

        self.main_ui = ui
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        self.messaging = get_plugin_by_type(PLUGIN_TYPE_MESSAGING)

        self.messaging.register_ui(self)

        self.community.community_gui.register_com_event('Chat', self.start_messaging_cb)

        self.display = []

        self.buffer = ''
        self.active_conversation = None

    def start_messaging_cb(self, target):
        if isinstance(target, User):
            c = self.messaging.open_user_conversation(target)
        elif isinstance(target, Community):
            c = self.messaging.open_community_conversation(target)

        self.set_active_conversation(c)
        self.main_ui.show_page(self)

    def set_active_conversation(self, conversation):
        self.active_conversation = conversation

    def handle_key(self, char):
        if char == ord('\n'):
            msg = self.buffer
            self.buffer = ''
            self.messaging.say(self.active_conversation, msg)
        else:
            self.buffer += chr(char)

    def draw(self):
        self.main_ui.screen.move(1, 0)
        self.main_ui.screen.clrtobot()

        (h, w) = self.main_ui.screen.getmaxyx()

        y = 1
        for msgid, text in self.display[-(h - 3):]:
            self.main_ui.screen.addstr(y, 0, text)
            y += 1

        self.main_ui.screen.addstr(h - 2, 0, ' ' * w, curses.color_pair(1))
        if self.active_conversation:
            (is_community, key, id) = decode_addr(self.active_conversation.target_addr)

            if is_community:
                coml = self.community.find_communities(id, peer=True)
                com = None
                if len(coml) > 0:
                    com = coml[0]
                name = id
            else:
                user = self.community.get_user(id)
                name = user.get('nick')
            self.main_ui.screen.addstr(h - 2, 1, name, curses.color_pair(1))
        self.main_ui.screen.addstr(h - 1, 0, self.buffer)

        self.main_ui.screen.refresh()
        return True

    def new_message_cb(self, conversation, msg):
        sender_addr = msg.get_sender_addr()
        # safe == False because messages sent by me also go through this path
        sender = user_from_addr(self.community, sender_addr, safe=False)
        if sender:
            sender_nick = sender.get('nick')
        else:
            sender_nick = TP_NICK_DEFAULT

        if self.active_conversation == conversation:
            self.display.append((msg.get_msgid(), '<%s> %s' % (sender_nick, msg.get_msg())))
            if self.main_ui.get_current_page() == self:
                self.draw()
        return True

    def delete_message_cb(self, conversation, msg):
        msgid = msg.get_msgid()
        # TODO

    def change_message_cb(self, conversation, msg):
        msgid = msg.get_msgid()
        # TODO

def init_ui(ui):
    Messaging_GUI(ui)
