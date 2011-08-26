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
from cursesui import Curses_Page
from proximateprotocol import PLUGIN_TYPE_COMMUNITY
from plugins import get_plugin_by_type

class Community_GUI(Curses_Page):
    def __init__(self, ui):
        Curses_Page.__init__(self, 'Home')

        self.main_ui = ui
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)

        self.community.register_ui(self)

        self.com_events = []
        self.user_events = []

        self.main_ui.show_page(self)

    def register_com_event(self, name, callback):
        self.com_events.append((name, callback))

    def register_user_event(self, name, callback):
        self.user_events.append((name, callback))

    def community_changes(self, com):
        pass

    def user_appears(self, user):
        if self.main_ui.get_current_page() == self:
            self.draw()

    def user_changes(self, user, what):
        if self.main_ui.get_current_page() == self:
            self.draw()

    def user_disappears(self, user):
        if self.main_ui.get_current_page() == self:
            self.draw()

    def handle_key(self, char):
        if char == ord('\n'):
            # hack
            name, callback = self.com_events[0]
            callback(self.community.get_default_community())

    def back_action(self):
        self.main_ui.quit()
        return True

    def draw(self):
        myself = self.community.get_myself()

        self.main_ui.screen.move(1, 0)
        self.main_ui.screen.clrtobot()

        (h, w) = self.main_ui.screen.getmaxyx()
        self.main_ui.screen.addstr(1, 0, '-' * w)
        self.main_ui.screen.addstr(1, 0, 'Communities ')

        communities = self.community.get_user_communities(myself)
        if self.community.personal_communities:
            communities += self.community.find_communities(peer=False)

        i = 0
        n = w // 30
        for com in communities:
            self.main_ui.screen.addstr(2 + i / n, i % n * 30, com.get('name'))
            i += 1

        self.main_ui.screen.addstr(h // 2, 0, '-' * w)
        self.main_ui.screen.addstr(h // 2, 0, 'Users ')

        users = self.community.get_users(True)
        i = 0
        for user in users:
            self.main_ui.screen.addstr(h // 2 + 1 + i / n, i % n * 30, user.get('nick'))
            i += 1
        self.main_ui.screen.move(0, 0)
        self.main_ui.screen.refresh()
        return True

def init_ui(ui):
    Community_GUI(ui)
