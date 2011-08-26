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
import gtk
import pango
from os.path import join, isfile, isdir, dirname, basename, exists
from mimetypes import guess_type

import sendfile_gui
from communitymeta import Community
from ioutils import filesize
from content import Content_Meta
from file_chooser_dlg import File_Chooser, FILE_CHOOSER_TYPE_FILE, FILE_CHOOSER_TYPE_DIR
from filesharing import Share_Meta, FTYPE_DIRECTORY, FTYPE_FILE
from general_dialogs import Download_Dialog
from guiutils import new_scrollarea, GUI_Page, Action_List
from openfile import open_file
from pathname import ICON_DIR, get_dir
from plugins import get_plugin_by_type
from proximateprotocol import PLUGIN_TYPE_COMMUNITY, PLUGIN_TYPE_SEND_FILE, \
    PLUGIN_TYPE_NOTIFICATION, PLUGIN_TYPE_FILE_SHARING, FS_PURPOSE_SHARE, \
    SHARE_DIR, SHARE_FILE
from support import debug, warning
from user import User
from utils import cut_text, format_bytes

community = None
filesharing = None
sendfile = None
main_gui = None
notification = None

MAX_GUI_NAME = 32

def split_keywords(s):
    keywords = []
    fields = s.split(',')
    for word in fields:
        newwords = word.split()
        keywords += newwords
    return keywords

class File_Sharing_GUI:
    """ File_Sharing_GUI class includes all the gui parts of the
    file sharing plugin. All communication between main gui and
    file sharing plugin should be done through this class.

    File_Sharing_GUI includes window for searching content, window
    for browsing user's content and window for publishing own content.
    Also, dialogs for adding meta information to a content are initialized
    through this class.
    """

    FILESHARING_ICON = '64px-search_content_icon.png'

    def __init__(self, gui, sendfilegui):
        global filesharing, community, sendfile, main_gui, notification
        filesharing = get_plugin_by_type(PLUGIN_TYPE_FILE_SHARING)
        community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        sendfile = get_plugin_by_type(PLUGIN_TYPE_SEND_FILE)
        notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)
        main_gui = gui
        self.sendfilegui = sendfilegui

        # store File_Sharing_Browse instances key = (target, is_community)
        self.browse_pages = {}

        # Initialize related pages
        self.fs_search = File_Sharing_Search(self)
        self.fs_results = File_Sharing_Browse(self, 'Search results')
        self.fs_publish = File_Sharing_Publish(self)

        icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), self.FILESHARING_ICON))
        community.community_gui.register_user_event(icon, 'Filesharing', self.start_filesharing_cb)
        community.community_gui.register_com_event(icon, 'Filesharing', self.start_filesharing_cb)

        main_gui.add_key_binding(gtk.gdk.CONTROL_MASK, gtk.keysyms.b, self.key_pressed_ctrl_b)

    def key_pressed_ctrl_b(self, target, ctx):
        iscom = isinstance(target, Community)
        self.show_browse_window(target, iscom)

    def start_filesharing_cb(self, target):
        if isinstance(target, User):
            self.start_filesharing_user_cb(target)
        elif isinstance(target, Community):
            self.start_filesharing_com_cb(target)

    def start_filesharing_user_cb(self, user):
        self.target = user
        self.com = False
        self.filesharing_dialog = Filesharing_Dialog(self.response_handler, user, False)

    def start_filesharing_com_cb(self, com):
        self.target = com
        self.com = True
        self.filesharing_dialog = Filesharing_Dialog(self.response_handler, com, True)

    def response_handler(self, widget, event, cmd_id):
        self.filesharing_dialog.dialog.set_modal(False)
        self.filesharing_dialog.dialog.destroy()

        function = None
        if cmd_id == Filesharing_Dialog.SEND_EVENT:
            function = self.sendfilegui.select_file_to_send
        elif cmd_id == Filesharing_Dialog.SEARCH_EVENT:
            function = self.fs_search.show_file_sharing_search
        elif cmd_id == Filesharing_Dialog.PUBLISH_EVENT:
            function = self.fs_publish.show_publish_window
        elif cmd_id == Filesharing_Dialog.BROWSE_EVENT:
            function = self.show_browse_window

        if function != None:
            function(self.target, self.com)

    def show_browse_window(self, target, is_community):
        key = (target, is_community)
        page = self.browse_pages.get(key)
        if page == None:
            page = File_Sharing_Browse(self, 'Browse content')
            self.browse_pages[key] = page
        page.show_browse_window(target, is_community)

class Filesharing_Dialog:
    """ Implements a dialog with possible actions for filesharing.

    Send file is also shown in this dialog although it is not implemented
    in this module.
    """

    SEND_ICON = '128px-send_file_icon.png'
    SEND_ICON_LOW = '128px-send-low-connection.png'
    SEND_ICON_NO = '128px-send-no-connection.png'
    SEARCH_ICON = '128px-search_files_icon.png'
    PUBLISH_ICON = '128px-publish_file_icon.png'
    BROWSE_ICON = '128px-browse_network_files_icon.png'
    CANCEL_ICON = '128px-cancel_icon.png'

    SEND_EVENT = 1
    SEARCH_EVENT = 2
    PUBLISH_EVENT = 3
    BROWSE_EVENT = 4
    CANCEL_EVENT = 5

    def __init__(self, response_handler_func, target, is_community):
        self.main_window = main_gui.get_main_window()
        self.dialog = gtk.Dialog('Filesharing', self.main_window)
        self.dialog.set_has_separator(False)
        self.response_handler = response_handler_func
        self.target = target
        self.is_community = is_community

        self.initialize_widgets()
        self.dialog.set_modal(True)
        self.dialog.show_all()

    def initialize_widgets(self):
        self.hbox = gtk.HBox()
        self.hbox.set_spacing(5)
        self.hbox.set_property("border-width", 0)

        send_ebox = gtk.EventBox()
        publish_ebox = gtk.EventBox()
        browse_ebox = gtk.EventBox()
        search_ebox = gtk.EventBox()
        cancel_ebox = gtk.EventBox()

        send_image = gtk.Image()
        publish_image = gtk.Image()
        browse_image = gtk.Image()
        search_image = gtk.Image()
        cancel_image = gtk.Image()

        # warn user of bad connectivity for sending files
        if not self.is_community:
            hops = self.target.get('hops')
            if hops == 2:
                send_icon = self.SEND_ICON_LOW
            elif hops > 2:
                send_icon = self.SEND_ICON_NO
            else:
                send_icon = self.SEND_ICON
        else:
            send_icon = self.SEND_ICON
        send_image.set_from_file(join(get_dir(ICON_DIR), send_icon))
        publish_image.set_from_file(join(get_dir(ICON_DIR), self.PUBLISH_ICON))
        browse_image.set_from_file(join(get_dir(ICON_DIR), self.BROWSE_ICON))
        search_image.set_from_file(join(get_dir(ICON_DIR), self.SEARCH_ICON))
        cancel_image.set_from_file(join(get_dir(ICON_DIR), self.CANCEL_ICON))

        send_ebox.add(send_image)
        publish_ebox.add(publish_image)
        browse_ebox.add(browse_image)
        search_ebox.add(search_image)
        cancel_ebox.add(cancel_image)

        send_ebox.connect("button-press-event", self.response_handler,
                          self.SEND_EVENT)
        publish_ebox.connect("button-press-event", self.response_handler,
                             self.PUBLISH_EVENT)
        browse_ebox.connect("button-press-event", self.response_handler,
                            self.BROWSE_EVENT)
        search_ebox.connect("button-press-event", self.response_handler,
                            self.SEARCH_EVENT)
        cancel_ebox.connect("button-press-event", self.response_handler,
                            self.CANCEL_EVENT)

        vbox1 = gtk.VBox()
        vbox2 = gtk.VBox()
        vbox3 = gtk.VBox()
        vbox4 = gtk.VBox()
        vbox5 = gtk.VBox()
        
        vbox1.pack_start(publish_ebox, True, True)
        vbox2.pack_start(browse_ebox, True, True)
        vbox3.pack_start(search_ebox, True, True)
        vbox4.pack_start(cancel_ebox, True, True)
        vbox5.pack_start(send_ebox, True, True)
        
        vbox1.pack_start(gtk.Label('Publish'), False, False)
        vbox2.pack_start(gtk.Label('Browse'), False, False)
        vbox3.pack_start(gtk.Label('Search'), False, False)
        vbox4.pack_start(gtk.Label('Cancel'), False, False)
        vbox5.pack_start(gtk.Label('Send File'), False, False)

        self.hbox.pack_start(vbox5, True, True)
        if self.is_community:
            self.hbox.pack_start(vbox1, True, True)
        self.hbox.pack_start(vbox2, True, True)
        self.hbox.pack_start(vbox3, True, True)
        self.hbox.pack_start(vbox4, True, True)

        self.dialog.vbox.pack_start(self.hbox, True, True, 0)
        self.dialog.action_area.set_size_request(0, 0)
        self.dialog.vbox.set_spacing(0)
        self.dialog.vbox.show_all()

class File_Sharing_Search(GUI_Page):
    """ File_Sharing_Search includes GUI window for searching user's
    files. The window is in two parts, first the search window is shown
    and after search is clicked the gui moves to the next window which shows
    the search results.

    Currently one limitation: multiple search windows can not be open
    at the same time. If a new window is opened the old one is replaced
    with the new one."""

    def __init__(self, fs_gui):
        GUI_Page.__init__(self, 'Search content')
        self.fs_gui = fs_gui
        self.target = None
        self.is_community = False

        self.vbox = gtk.VBox()
        self.pack_start(self.vbox)

        self.entries = {}
        self.initialize_search_window()
        self.initialize_action_list()
        
        self.title = gtk.Label('Search Content')
        self.vbox.pack_start(self.title, False, False)
        self.vbox.pack_start(gtk.HSeparator(), False, False)
        self.vbox.pack_start(self.search_fwindow, True, True)

        self.show_all()
        main_gui.add_page(self)

    def initialize_search_window(self):
        self.search_fwindow = new_scrollarea()
        self.search_vbox = gtk.VBox()
        self.search_fwindow.add_with_viewport(self.search_vbox)

        entrylist = [('keywords', 'Keywords:'), \
                     ('fname', 'Filename:'), \
                     ('title', 'Title:'), \
                     ('author', 'Author:'), \
                     ('description', 'Description:')]

        for (key, header) in entrylist:
            hbox = gtk.HBox()
            label = gtk.Label(header)
            label.set_size_request(130, -1)
            label.set_alignment(0, 0)
            hbox.pack_start(label, False, False)

            entry = gtk.Entry()
            self.entries[key] = entry
            entry.connect("activate", self.search_cb)
            hbox.pack_start(entry, True, True)
            self.search_vbox.pack_start(hbox, False, False)

    def initialize_action_list(self):
        search_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), "64px-search_content_icon.png"))
        remove_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), "64px-remove_content_icon.png"))

        action_buttons = [(search_icon, 'Search', self.search_cb),
                          (remove_icon, 'Clear', self.clear_cb)
                         ]

        self.actions = Action_List()

        for action in action_buttons:
            (icon, text, cb) = action
            self.actions.add_button(icon, text, cb)

        self.pack_start(self.actions.get_widget(), False, True)

    def clear_cb(self, widget):
        for (key, entry) in self.entries.items():
            entry.set_text('')
        self.entries['keywords'].grab_focus()

    def search_cb(self, widget):
        query = {}
        for (key, entry) in self.entries.items():
            query[key] = entry.get_text()

        keywords = None
        criteria = []

        text = self.entries['keywords'].get_text().strip()
        if text != '':
            keywords = split_keywords(text)
            if len(keywords) == 0:
                keywords = None

        for field in ['fname', 'title', 'author', 'description']:
            text = self.entries[field].get_text().strip()
            if text != '':
                criteria.append((field, text))
        if len(criteria) == 0:
            criteria = None

        self.fs_gui.fs_results.show_browse_window(self.target, self.is_community, criteria=criteria, keywords=keywords)

    def show_file_sharing_search(self, target, is_community):
        """ Opens the whole file sharing window."""

        if is_community:
            target_name = target.get('name')
        else:
            target_name = target.get('nick')

        self.is_community = is_community
        self.target = target

        self.title.set_text('Search content from: %s' % target_name)

        self.entries['keywords'].set_property("can-focus", True)

        self.set_page_title(target_name, sub=True)
        main_gui.show_page(self)
        self.entries['keywords'].grab_focus()
        
class File_Sharing_Browse(GUI_Page):
    """ File_Sharing_Browse includes GUI window for browsing user's
    file shares. """

    COL_SHAREMETA = 0
    COL_SHAREPATH = 1
    COL_USER = 2
    COL_TYPE = 3
    COL_ICON = 4
    COL_GUINAME = 5
    COL_NICK = 6
    COL_SIZE = 7
    COL_COLOR = 8 # internal attribute: depends on hop count
    COL_HOPS = 9

    # colors for different hopcounts: 0 = 1 = foreground color, 2 = yellow, 3 or more = red
    HOP_COLORS = [None, None, "yellow", "red"]

    def __init__(self, fs_gui, title):
        GUI_Page.__init__(self, title)
        self.fs_gui = fs_gui
        self.target = None
        self.is_community = False
        self.items = 0

        self.vbox = gtk.VBox()
        self.pack_start(self.vbox)

        self.folders = {}

        self.content_list = gtk.TreeStore(gobject.TYPE_PYOBJECT, str, gobject.TYPE_PYOBJECT, bool, gtk.gdk.Pixbuf, str, str, str, str, int)
        self.content_list.set_sort_column_id(self.COL_HOPS, gtk.SORT_ASCENDING)

        self.initialize_browse_list()
        self.initialize_action_list()

        self.title = gtk.Label("Content Browsing")
        self.vbox.pack_start(self.title, False, False)
        scrollwin = new_scrollarea()
        scrollwin.add_with_viewport(self.browse_list_view)
        self.vbox.pack_start(scrollwin, True, True)

        self.show_all()
        main_gui.add_page(self)

    def back_action(self):
        if self == self.fs_gui.fs_results:
            return False
        key = (self.target, self.is_community)
        self.fs_gui.browse_pages.pop(key)
        main_gui.remove_page(self)
        self.destroy()
        return True

    def initialize_browse_list(self):
        self.browse_list_view = gtk.TreeView(self.content_list)
        # self.browse_list_view.get_selection().set_mode(gtk.SELECTION_MULTIPLE)
        self.browse_list_view.set_headers_visible(False)

        column = gtk.TreeViewColumn('')
        self.browse_list_view.append_column(column)
        column.set_expand(True)
        cr_icon = gtk.CellRendererPixbuf()
        cr_guiname = gtk.CellRendererText()
        column.pack_start(cr_icon, False)
        column.pack_start(cr_guiname)
        column.add_attribute(cr_icon, 'pixbuf', self.COL_ICON)
        column.add_attribute(cr_guiname, 'text', self.COL_GUINAME)
        column.add_attribute(cr_guiname, 'foreground', self.COL_COLOR)

        column = gtk.TreeViewColumn('')
        self.browse_list_view.append_column(column)
        cr_nick = gtk.CellRendererText()
        column.pack_start(cr_nick)
        column.add_attribute(cr_nick, 'text', self.COL_NICK)

        column = gtk.TreeViewColumn('')
        self.browse_list_view.append_column(column)
        cr_size = gtk.CellRendererText()
        column.pack_start(cr_size)
        column.add_attribute(cr_size, 'text', self.COL_SIZE)

    def initialize_action_list(self):
        download_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), "64px-browse_content_icon.png"))
        open_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), "64px-publish_content_icon.png"))
        metadata_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), "64px-edit_metadata_icon.png"))
        search_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), "64px-search_content_icon.png"))

        action_buttons = [(download_icon, 'Download', self.download_cb),
                          (open_icon, 'Stream', self.stream_cb),
                          (metadata_icon, 'Show\nMetadata', self.show_metadata_cb),
                          (search_icon, 'Search\nFrom User', self.show_search_cb),
                          (search_icon, 'Refresh', self.refresh_cb)
                         ]

        self.actions = Action_List()

        for action in action_buttons:
            (icon, text, cb) = action
            self.actions.add_button(icon, text, cb)

        self.pack_start(self.actions.get_widget(), False, True)

    def download_cb(self, widget):
        model, selected = self.browse_list_view.get_selection().get_selected_rows()
        if len(selected) == 0:
            notification.notify('No file selected!', highpri=True)
            return
        row = self.content_list[selected[0]]

        meta = row[self.COL_SHAREMETA]
        user = row[self.COL_USER]
        sharepath = row[self.COL_SHAREPATH]
        guiname = row[self.COL_GUINAME]
        directory = row[self.COL_TYPE]

        if directory:
            what = 'directory'
        else:
            what = 'file'

        ctx = (user, meta['id'], sharepath, directory, meta)
        Download_Dialog(main_gui.get_main_window(),
                        'Download a %s' % what,
                        'Downloading a %s from %s: %s' % (what, user.tag(), guiname),
                        self.download_dialog_cb, ctx)

    def download_dialog_cb(self, accept, open_content, ctx):
        if not accept:
            return

        (user, shareid, sharepath, directory, meta) = ctx

        name = basename(sharepath)
        if directory and name == '' and meta.get('description'):
            name = meta.get('description')

        destname = filesharing.get_download_path(name)

        if directory:
            ctx = (sharepath, destname, name)
            if not filesharing.query(user, self.download_results, ctx, shareid=shareid, sharepath=sharepath):
                notification.notify('Unable to list directory contents from %s' % user.tag(), True)
            return

        notification.notify('Trying to download from %s' % user.tag())
        ctx = (user, destname, sharepath, open_content)
        if not filesharing.get_files(user, basename(sharepath), [(shareid, sharepath, destname)], download_complete, ctx):
            notification.ok_dialog('File sharing',
                'Unable to download a file from %s: %s' % (user.tag(), name))

    def download_results(self, user, allresults, metadict, ctx):
        (rootpath, destpath, name) = ctx

        if allresults == None:
            notification.notify('Unable to list directory contents from %s' % user.tag(), True)
            return

        files = []
        totallen = 0
        for (shareid, sharepath, fsize, ftype) in allresults:
            # NOTE: The sharepath should begin with rootpath
            i = len(rootpath)
            while i < len(sharepath):
                if sharepath[i] != '/':
                    break
                i += 1
            destname = join(destpath, sharepath[i:])
            files.append((shareid, sharepath, destname))
            totallen += fsize
        if not filesharing.get_files(user, name + '/', files, None, totallen=totallen):
            notification.ok_dialog('File sharing',
                'Unable to download a directory from %s: %s' % (user.tag(), name))

    def show_metadata_cb(self, widget):
        model, selected = self.browse_list_view.get_selection().get_selected_rows()
        if len(selected) == 0:
            notification.notify('No file selected!', highpri=True)
            return
        row = self.content_list[selected[0]]

        meta = row[self.COL_SHAREMETA]
        user = row[self.COL_USER]
        sharepath = row[self.COL_SHAREPATH]
        guiname = row[self.COL_GUINAME]
        shareid = meta['id']

        ctx = (user, guiname)
        filesharing.get_metas(user, [(shareid, sharepath)], self.got_metadata_for_file, ctx)
        filesharing.progress_update('Getting metadata for content...')

    def got_metadata_for_file(self, metas, ctx):
        (user, guiname) = ctx

        filesharing.progress_update(None)

        if len(metas) == 0:
            msg = 'No metadata for file: %s' %(guiname)
            notification.ok_dialog('Filesharing', msg)
            return

        if len(metas) != 1:
            debug('FileSharing: Found too many metadatas for file\n')
            return

        (shareid, fname, meta) = metas[0]

        Show_Metadata_Dialog(main_gui.get_main_window(), guiname, meta)

    def show_browse_window(self, target, is_community, criteria=None, keywords=None):
        if is_community:
            target_name = target.get('name')
        else:
            target_name = target.get('nick')

        self.is_community = is_community
        self.target = target
        self.criteria = criteria
        self.keywords = keywords

        self.set_page_title(target_name, sub=True)
        main_gui.show_page(self)
        self.update_content_list()
    
    def show_search_cb(self, widget):
        model, selected = self.browse_list_view.get_selection().get_selected_rows()
        if len(selected) == 0:
            notification.notify('No file selected!', highpri=True)
            return
        row = self.content_list[selected[0]]

        user = row[self.COL_USER]
        self.fs_gui.fs_search.show_file_sharing_search(user, False)

    def stream_cb(self, widget):
        model, selected = self.browse_list_view.get_selection().get_selected_rows()
        if len(selected) == 0:
            notification.notify('No file selected!', highpri=True)
            return
        row = self.content_list[selected[0]]

        meta = row[self.COL_SHAREMETA]
        user = row[self.COL_USER]
        sharepath = row[self.COL_SHAREPATH]

        filesharing.stream(user, meta['id'], sharepath)
        notification.notify('Trying to stream from %s' % user.tag())

    def update_content_list(self):
        self.content_list.clear()
        self.folders = {}

        self.items = 0
        self.title.set_text('No content found')

        if not self.is_community:
            if self.target == community.get_myself():
                # do not fetch own shares
                return
            if not filesharing.query(self.target, self.query_results, criteria=self.criteria, keywords=self.keywords):
                notification.notify('Unable to query shares from %s' % self.target.tag(), True)

        else: # Community
            filesharing.query_community(self.target, self.query_results, criteria=self.criteria, keywords=self.keywords)

    def refresh_cb(self, widget):
        self.update_content_list()

    def query_results(self, user, allresults, metadict, ctx):
        if allresults == None:
            notification.notify('Unable to query shares from %s' % user.tag(), True)
            return

        for (shareid, sharepath, fsize, ftype) in allresults:
            meta = metadict[shareid]

            size = ''
            if ftype == FTYPE_FILE:
                size = format_bytes(fsize)
            self.add_item(meta, user, shareid, sharepath, size, ftype == FTYPE_DIRECTORY)
            self.items += 1

        self.title.set_text('Showing %d items' % self.items)

    def add_item(self, meta, user, shareid, sharepath, fsize, directory):
        key = (user, shareid, sharepath)
        riter = self.folders.get(key)
        if riter != None:
            return riter

        if sharepath != '/' and meta.get('type') == SHARE_DIR:
            parent_path = dirname(sharepath)
            parent = self.add_item(meta, user, shareid, parent_path, '', True)
        else:
            parent = None

        guiname = basename(sharepath)

        if directory:
            filetype = 'folder'
            if guiname == '' and meta.get('description'):
                guiname = meta.get('description')
            guiname += '/'
        else:
            filetype = get_filetype(sharepath)

        guiname = cut_text(guiname, MAX_GUI_NAME)

        ft_icon = get_filetype_icon(filetype)
        nick = user.get('nick')
        hops = user.get('hops')
        if hops == None:
            hops = 0
        if hops < 4:
            color = self.HOP_COLORS[hops]
        else:
            color = self.HOP_COLORS[3]
        riter = self.content_list.append(parent, [meta, sharepath, user, directory, ft_icon, guiname, nick, fsize, color, hops])

        if directory:
            self.folders[key] = riter

        return riter

class Show_Metadata_Dialog:

    def __init__(self, main_gui_window, guiname, meta):
        self.meta = meta

        self.dialog = gtk.Dialog('%s\'s Metadata' %guiname, main_gui_window,
                                 gtk.DIALOG_DESTROY_WITH_PARENT | gtk.DIALOG_MODAL,
                                 (gtk.STOCK_OK, gtk.RESPONSE_OK))
        self.dialog.set_border_width(5)
        self.dialog.vbox.set_spacing(2)

        self.meta_widgets = {}

        self.initialize_widgets()

        self.dialog.connect("response", self.response_handler)
        self.dialog.show_all()

    def response_handler(self, widget, event):
        self.dialog.destroy()

    def initialize_widgets(self):
        main_vbox = gtk.VBox()

        meta_components = (('title', 'Title:'),
                     ('keywords', 'Keywords:'),
                     ('author', 'Author:'),
                     ('year', 'Year:'),
                     ('type', 'File type:'),
                     ('description', 'Description:'))

        has_metadata = False
        for (key, header) in meta_components:
            value = self.meta.get(key)
            if value == None or value == []:
                continue

            has_metadata = True
            text = str(value)

            hbox = gtk.HBox()
            label = gtk.Label(header)
            label.set_size_request(150, -1)
            label.set_alignment(0, 0)
            label.modify_font(pango.FontDescription("Bold"))
            hbox.pack_start(label, False, False)

            label = gtk.Label(text)
            label.set_size_request(250, -1)
            label.set_alignment(0, 0)
            label.set_line_wrap(True)

            hbox.pack_start(label, True, True)
            main_vbox.pack_start(hbox, False, False)

        if not has_metadata:
            main_vbox.pack_start(gtk.Label('Empty metadata'))

        self.dialog.vbox.add(main_vbox)

class Edit_Metadata_Dialog:

    def __init__(self, main_gui_window, shareid, guiname, sharepath, fs_gui):
        self.fs_gui = fs_gui
        self.share = filesharing.get_share(shareid)
        if self.share == None:
            warning('Bad share in Edit_Metadata_Dialog %d\n' % shareid)
            return
        self.sharepath = sharepath
        self.meta = self.share.get_filemeta(self.sharepath, forceread=True)
        if self.meta == None:
            self.meta = Content_Meta()

        self.dialog = gtk.Dialog('Edit %s\'s Metadata' %(guiname), main_gui_window,
                                 gtk.DIALOG_DESTROY_WITH_PARENT | gtk.DIALOG_MODAL,
                                 (gtk.STOCK_OK, gtk.RESPONSE_OK,
                                 gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL))
        self.dialog.set_border_width(5)
        self.dialog.vbox.set_spacing(2)

        self.meta_widgets = {}

        self.initialize_widgets()

        self.dialog.connect("response", self.response_handler)
        self.dialog.show_all()

    def response_handler(self, widget, event):
        if event == gtk.RESPONSE_OK:
            self.update_content_metadata()

        self.dialog.destroy()

    def initialize_widgets(self):
        main_vbox = gtk.VBox()

        meta_components = (('title', 'Title:'),
                     ('keywords', 'Keywords:'),
                     ('author', 'Author:'),
                     ('year', 'Year:'),
                     ('type', 'File type:'),
                     ('description', 'Description:'))

        filetypes = ('application', 'audio', 'image', 'text', 'video')

        for (key, header) in meta_components:
            hbox = gtk.HBox()
            label = gtk.Label(header)
            label.set_size_request(150, -1)
            label.set_alignment(0, 0.5)
            hbox.pack_start(label, False, False)

            value = self.meta.get(key)

            text = ''
            if value != None:
                text = str(value)

            if key == 'type': # create dropdown box separately
                widget = gtk.combo_box_entry_new_text()
                for type in filetypes:
                    widget.append_text(type)
                entry = widget.child
                entry.set_text(text)
                self.meta_widgets[key] = entry
            else:
                widget = gtk.Entry()
                widget.set_text(text)
                self.meta_widgets[key] = widget
            widget.set_size_request(250, -1)
            hbox.pack_start(widget, True, True)
            main_vbox.pack_start(hbox, False, False)

        self.dialog.vbox.add(main_vbox)

    def update_content_metadata(self):
        for (key, widget) in self.meta_widgets.items():
            value = widget.get_text() 
            if value == '':
                value = None

            self.meta.set(key, value)

        self.share.update_meta(self.sharepath, self.meta)

class File_Sharing_Publish(GUI_Page):
    """ File_Sharing_Publish includes GUI window for adding shares. """

    COL_SHAREMETA = 0
    COL_SHAREPATH = 1
    COL_TYPE = 2
    COL_ICON = 3
    COL_GUINAME = 4
    COL_SIZE = 5

    def __init__(self, fs_gui):
        GUI_Page.__init__(self, 'Publish content')
        self.fs_gui = fs_gui

        self.icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), \
                                                      "64px-publish_content_icon.png"))
    
        self.vbox = gtk.VBox()
        self.pack_start(self.vbox)

        self.folders = {}

        self.sharelist = gtk.TreeStore(gobject.TYPE_PYOBJECT, str, bool, gtk.gdk.Pixbuf, str, str)

        self.initialize_share_list()
        self.initialize_action_list()

        self.title = gtk.Label("Content Publishing")
        self.vbox.pack_start(self.title, False, False)
        scrollwin = new_scrollarea()
        scrollwin.add_with_viewport(self.sharelist_view)
        self.vbox.pack_start(scrollwin, True, True)

        self.show_all()
        main_gui.add_page(self)

    def initialize_share_list(self):
        self.sharelist_view = gtk.TreeView(self.sharelist)
        self.sharelist_view.set_headers_visible(False)

        column = gtk.TreeViewColumn('')
        self.sharelist_view.append_column(column)
        column.set_expand(True)
        cr_icon = gtk.CellRendererPixbuf()
        cr_guiname = gtk.CellRendererText()
        column.pack_start(cr_icon, False)
        column.pack_start(cr_guiname)
        column.add_attribute(cr_icon, 'pixbuf', self.COL_ICON)
        column.add_attribute(cr_guiname, 'text', self.COL_GUINAME)

        column = gtk.TreeViewColumn('')
        self.sharelist_view.append_column(column)
        cr_size = gtk.CellRendererText()
        column.pack_start(cr_size)
        column.add_attribute(cr_size, 'text', self.COL_SIZE)

    def initialize_action_list(self):
        add_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), "64px-add_content_icon.png"))
        remove_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), "64px-remove_content_icon.png"))
        open_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), "64px-publish_content_icon.png"))
        metadata_icon = gtk.gdk.pixbuf_new_from_file(join(get_dir(ICON_DIR), "64px-edit_metadata_icon.png"))

        action_buttons = [(add_icon, 'Publish\nFile', self.add_file_cb),
                          (add_icon, 'Publish\nDirectory', self.add_dir_cb),
                          (remove_icon, 'Remove', self.remove_cb),
                          (open_icon, 'Open', self.open_cb),
                          (metadata_icon, 'Edit\nMetadata', self.edit_metadata_cb)
                         ]

        self.actions = Action_List()

        for action in action_buttons:
            (icon, text, cb) = action
            self.actions.add_button(icon, text, cb)

        self.pack_start(self.actions.get_widget(), False, True)
            
    def show_publish_window(self, target, is_community):
        if is_community:
            target_name = target.get('name')
        else:
            target_name = target.get('nick')

        self.sharelist_view.set_model(self.sharelist)
        self.sharelist_view.show_all()
        
        self.title.set_text('Share Content with %s' %(target_name))

        self.update_sharelist()
        
        main_gui.show_page(self)

    def add_file_cb(self, widget):
        File_Chooser(main_gui.get_main_window(), FILE_CHOOSER_TYPE_FILE, True, self.add_file_chooser_cb)

    def add_file_chooser_cb(self, filenames, ctx):
        if filenames == None:
            return

        for f in filenames:
            if isfile(f):
                sharemeta = Share_Meta()
                sharemeta.set('description', basename(f))
                filesharing.add_share(f, sharemeta=sharemeta, stype=SHARE_FILE)
            else:
                warning('Invalid filename from file chooser dialog\n')

        self.update_sharelist()

    def add_dir_cb(self, widget):
        File_Chooser(main_gui.get_main_window(), FILE_CHOOSER_TYPE_DIR, False, self.add_dir_chooser_cb)

    def add_dir_chooser_cb(self, dir_name, ctx):
        if dir_name == None:
            return

        if isdir(dir_name):
            sharemeta = Share_Meta()
            sharemeta.set('description', basename(dir_name))
            filesharing.add_share(dir_name, sharemeta=sharemeta, stype=SHARE_DIR)
        else:
            warning('Invalid dirname from file chooser dialog\n')

        self.update_sharelist()

    def open_cb(self, widget):
        model, selected = self.sharelist_view.get_selection().get_selected_rows()
        if len(selected) == 0:
            notification.notify('No file selected!', highpri=True)
            return
        row = self.sharelist[selected[0]]

        meta = row[self.COL_SHAREMETA]
        sharepath = row[self.COL_SHAREPATH]
        guiname = row[self.COL_GUINAME]
        shareid = meta['id']

        fullpath = filesharing.native_path(shareid, sharepath)
        if fullpath == None:
            warning('FileSharingGUI: Can not open shareid %d sharepath %s\n' %(shareid, sharepath))
            return

        notification.notify('Opening content %s' %(guiname))

        if not open_file(fullpath):
            notification.ok_dialog('Can not open file', 'Can not open file: %s\nUnknown format, or not supported.' %(fullpath))

    def remove_cb(self, widget):
        model, selected = self.sharelist_view.get_selection().get_selected_rows()
        if len(selected) == 0:
            notification.notify('No share selected!', highpri=True)
            return
        row = self.sharelist[selected[0]]

        meta = row[self.COL_SHAREMETA]
        shareid = meta['id']
        filesharing.remove_share(filesharing.get_share(shareid))

        self.update_sharelist()
        
    def edit_metadata_cb(self, widget):
        model, selected = self.sharelist_view.get_selection().get_selected_rows()
        if len(selected) == 0:
            notification.notify('No share selected!', highpri=True)
            return
        row = self.sharelist[selected[0]]

        meta = row[self.COL_SHAREMETA]
        sharepath = row[self.COL_SHAREPATH]
        guiname = row[self.COL_GUINAME]
        shareid = meta['id']

        Edit_Metadata_Dialog(main_gui.get_main_window(), shareid, guiname, sharepath, self)

    def update_sharelist(self):
        self.sharelist.clear()
        self.folders = {}

        for (shareid, share) in filesharing.shares.items():
            for (sharepath, ftype) in share.list_recursively().items():
                size = ''
                if ftype == FTYPE_FILE:
                    nativepath = share.native_path(sharepath)
                    size = format_bytes(filesize(nativepath))
                self.add_item(share.meta, shareid, sharepath, size, ftype == FTYPE_DIRECTORY)

    def add_item(self, meta, shareid, sharepath, fsize, directory):
        key = (shareid, sharepath)
        riter = self.folders.get(key)
        if riter != None:
            return riter

        if sharepath != '/' and meta.get('type') == SHARE_DIR:
            parent_path = dirname(sharepath)
            parent = self.add_item(meta, shareid, parent_path, '', True)
        else:
            parent = None

        guiname = basename(sharepath)

        if directory:
            filetype = 'folder'
            if guiname == '' and meta.get('description'):
                guiname = meta.get('description')
            guiname += '/'
        else:
            filetype = get_filetype(sharepath)

        guiname = cut_text(guiname, MAX_GUI_NAME)

        ft_icon = get_filetype_icon(filetype)
        riter = self.sharelist.append(parent, [meta, sharepath, directory, ft_icon, guiname, fsize])

        if directory:
            self.folders[key] = riter

        return riter

def download_complete(success, ctx):
    (user, destname, sharepath, open_content) = ctx
    if success and open_content:
         if not open_file(destname):
             notification.ok_dialog('Can not open file',
                 'Can not open file: %s\nUnknown format, or not supported.' % (destname))
    if not success:
        notification.ok_dialog('File sharing',
            'Unable to download a file from %s: %s' % (user.tag(), sharepath))

def get_filetype(sharepath):
    (mimetype, encoding) = guess_type(sharepath)
    if not mimetype:
        return None
    return mimetype.split('/')[0]

def get_filetype_icon(filetype):
    ft_default = '32px-Text-x-generic-template.png'
    ft_icons = {'application': '32px-Applications-system.png',
        'audio': '32px-Audio-x-generic.png',
        'image': '32px-Image-x-generic.png',
        'text': '32px-Text-x-generic.png',
        'video': '32px-Video-x-generic.png',
        'folder': '32px-Folder.png',
        'remotefolder': '32px-Folder-remote.png',
        'remotefolder-low': 'send-low-connection.png',
        'remotefolder-no': 'send-no-connection.png',
        None: ft_default }

    ft_icon_path = join(get_dir(ICON_DIR), ft_icons.get(filetype, ft_default))
    return gtk.gdk.pixbuf_new_from_file(ft_icon_path)

def init_ui(main_gui):
    # We need to know about sendfile GUI, because the send action is started
    # from our GUI
    sendfilegui = sendfile_gui.init_ui(main_gui)
    File_Sharing_GUI(main_gui, sendfilegui)
