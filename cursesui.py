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
import gobject
import curses
import sys

from support import die

class Curses_Page:
    def __init__(self, title):
        self.title = title
        self.is_visible = False

    def draw(self):
        pass

    def back_action(self):
        return False

class Curses_UI:
    def __init__(self):
        self.main_loop = gobject.MainLoop()

        self.screen = curses.initscr()
        self.screen.nodelay(1)

        curses.start_color()
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)

        gobject.io_add_watch(sys.stdout, gobject.IO_IN, self.stdin_read)

        self.page_history = []

    def stdin_read(self, fd, cond):
        char = self.screen.getch()
        if char == 24: # ctrl-x
            self.go_back_one_page(self.page_history[-1])
        else:
            self.page_history[-1].handle_key(char)
        return True

    def quit(self):
        curses.endwin()
        self.main_loop.quit()

    def go_back_one_page(self, page):
        if not page.back_action():
            self.hide_page(page)

    def show_page(self, page):
        if page.is_visible:
            self.page_history.remove(page)
        self.page_history.append(page)
        self.set_visible_page(page)
        page.is_visible = True

    def set_visible_page(self, page):
        (h, w) = self.screen.getmaxyx()
        self.screen.addstr(0, 0, ' ' * w, curses.color_pair(1))
        self.screen.addstr(0, 1, 'Proximate: %s (^X: go back)' % page.title, curses.color_pair(1))
        page.draw()

    def hide_page(self, page):
        if page == self.page_history[-1]:
            # currently visible page, go to the previous one
            self.set_visible_page(self.page_history[-2])
        self.page_history.remove(page)
        page.is_visible = False

    def get_current_page(self):
        return self.page_history[-1]

    def run(self):
        self.main_loop.run()

def run_ui():
    """ Start Curses User Interface """

    main_ui = Curses_UI()

    for modulename in ['community_curses', 'messaging_curses']:
        module = __import__(modulename)
        try:
            module.init_ui(main_ui)
        except TypeError:
            die('Curses module %s init() called with invalid arguments\n' %(modulename))

    main_ui.run()
