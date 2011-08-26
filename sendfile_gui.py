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
from os.path import basename, join, isfile

from plugins import get_plugin_by_type
from proximateprotocol import PLUGIN_TYPE_COMMUNITY, PLUGIN_TYPE_SEND_FILE, \
    PLUGIN_TYPE_NOTIFICATION, PLUGIN_TYPE_FILE_SHARING
from file_chooser_dlg import File_Chooser, FILE_CHOOSER_TYPE_FILE
from general_dialogs import Download_Dialog
from openfile import open_file

class Send_File_GUI:
    def __init__(self, gui):
        self.main_gui = gui
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        self.sendfile = get_plugin_by_type(PLUGIN_TYPE_SEND_FILE)
        self.notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)
        self.filesharing = get_plugin_by_type(PLUGIN_TYPE_FILE_SHARING)

        self.sendfile.receive_cb.append(self.display_receive)

    def select_file_to_send(self, target, is_community):
        """Selecting the file to be sent by using the file chooser dialog
        """

        if not is_community:
            if target == self.community.get_myself():
                self.notification.notify("Error: Trying to send a file to yourself", True)
                return

        ctx = (target, is_community)
        File_Chooser(self.main_gui.get_main_window(), FILE_CHOOSER_TYPE_FILE, False, self.select_file_chooser_cb, ctx)

    def select_file_chooser_cb(self, filename, ctx):
        if filename == None:
            # Cancel clicked
            return

        (target, is_community) = ctx
        if isfile(filename):
            self.transfer_selected_file(target, filename, is_community)
        else:
            warning("GUI: Invalid filename from file chooser dialog\n")
    
    def transfer_selected_file(self, target, filename, is_community):
        """This function is used, when the user wants to send a file that
        he/she has selected before or received earlier.
        """
        # checking that the file is ok to send
        try:
            f = open(filename, 'r')
        except IOError, (errno, strerror):
            warning("GUI: Can not open and send file '%s': %s" %(filename, strerror))
            return
        f.close()

        if not is_community:
            self.sendfile.send(target, filename)
        else:
            # the following function should contain a return value
            # in future, so that the user can be informed
            self.send_file_to_community(filename, target)

    def send_file_to_community(self, filename, community):
        """This function handles the send operation, when the target
        is a community instead of a single user.
        """

        # myself is not an active user
        users = self.community.get_community_members(community)

        if len(users) == 0:
            self.notification.notify('The chosen community is empty', True)
            return

        for user in users:
            if not self.sendfile.send(user, filename):
                break

    def display_receive(self, cb, user, fname):
        ctx = (cb, fname)
        Download_Dialog(
                    self.main_gui.get_main_window(),
                    'File send',
                    '%s wants to send you a file: %s' % (user.tag(), fname),
                    self.download_dialog_cb, ctx)

    def download_dialog_cb(self, accept, open_content, ctx):
        (cb, fname) = ctx
        if not accept:
            cb(False, None, None)
            return

        destname = self.filesharing.get_download_path(fname)

        ctx = (destname, open_content)
        cb(True, destname, self.download_cb, ctx)

    def download_cb(self, success, ctx):
        (destname, open_content) = ctx
        if success and open_content:
             if not open_file(destname):
                 notification.ok_dialog('Can not open file',
                     'Can not open file: %s\nUnknown format, or not supported.' % (destname))

def init_ui(main_gui):
    return Send_File_GUI(main_gui)
