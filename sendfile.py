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
import os

from bencode import fmt_bdecode, bencode
from ioutils import get_flen, TCP_Queue, TCPQ_ERROR
from plugins import Plugin, get_plugin_by_type
from support import warning
from proximateprotocol import TP_SEND_FILE, valid_receive_name, \
     PLUGIN_TYPE_COMMUNITY, PLUGIN_TYPE_SEND_FILE, \
     TP_CONNECT_TIMEOUT, PLUGIN_TYPE_NOTIFICATION, \
     PLUGIN_TYPE_FILE_TRANSFER, TP_MAX_TRANSFER
from utils import format_bytes

SEND_FILE_ACCEPT = 'mkay'
SEND_FILE_DENY = 'nothx'

community = None
notify = None
sendfile = None

ACCEPT_TIMEOUT = 300

class Send_File_Server:
    """ Process incoming sendfile connection """

    sendspec = {'uid': str,
                'flen': lambda flen: (type(flen) == int or type(flen) == long) and flen >= 0,
                'name': valid_receive_name,
               }

    def __init__(self, address, sock, data):
        self.q = TCP_Queue(self.msghandler, closehandler=self.queue_closed)

        # Close queue that is idle for a period of time
        self.q.set_timeout(ACCEPT_TIMEOUT)

        self.address = address
        self.initstate = True
        self.f = None
        self.ui = None
        self.pos = 0
        self.user = None
        self.name = None
        self.flen = None
        self.cb = None
        self.ctx = None

        self.q.append_input(data)
        self.q.initialize(sock)

    def queue_closed(self, q, parameter, msg):
        if self.f != None:
            self.f.close()
            self.f = None
        if self.ui != None:
            self.ui.cleanup('End')
            self.ui = None
        if self.cb != None:
            self.cb(self.pos == self.flen, self.ctx)
            self.cb = None
        if self.name != None and self.pos < self.flen:
            notify('Unable to receive a file from %s: %s' % (self.user.get('nick'), self.name), True)
        self.name = None

    def msghandler(self, q, data, parameter):
        if not self.initstate:
            warning('send file server: protocol violation!\n')
            return False

        self.initstate = False

        d = fmt_bdecode(self.sendspec, data)
        if d == None:
            warning('send file server: invalid msg: %s\n' % data)
            return False
        self.user = community.safe_get_user(d['uid'], self.address[0])
        if self.user == None:
            warning('send file server: invalid uid: %s\n' % d['uid'])
            return False

        self.name = d['name']
        self.flen = d['flen']

        notify('Got a file send request from %s: %s (%s)' % (self.user.get('nick'), self.name, format_bytes(self.flen)))

        for cb in sendfile.receive_cb:
            cb(self.accept_send, self.user, self.name)
        return True

    def abort_cb(self, ctx):
        self.q.close(msg='Aborted')

    def accept_send(self, accept, destname, cb, ctx=None):
        """ callback(success, bytes, ctx) """

        if self.name == None:
            # Aborted
            return

        if not accept:
            self.q.write(SEND_FILE_DENY)
            self.q.close_after_send('File denied')
            return

        filetransfer = get_plugin_by_type(PLUGIN_TYPE_FILE_TRANSFER)
        if filetransfer != None:
            title = 'Receiving from %s: %s' % (self.user.get('nick'), self.name)
            self.ui = filetransfer.add_transfer(title, self.flen, self.abort_cb)

        self.q.set_timeout(TP_CONNECT_TIMEOUT)

        self.cb = cb
        self.ctx = ctx

        self.q.write(SEND_FILE_ACCEPT)

        try:
            self.f = open(destname, 'w')
        except IOError, (errno, strerror):
            self.q.close(TCPQ_ERROR, msg=strerror)
            return

        self.q.set_recv_handler(self.receive)

    def receive(self, data):
        amount = min(len(data), self.flen - self.pos)

        try:
            self.f.write(data[0:amount])
        except IOError, (errno, strerror):
            self.q.close(TCPQ_ERROR, msg=strerror)
            return None

        self.pos += amount

        if self.ui != None:
            self.ui.update(amount)

        if self.flen == self.pos:
            notify('Received a file from %s succefully: %s' % (self.user.get('nick'), self.name))
            self.q.close(msg='Complete')
            return None

        return amount

class Send_File:
    def __init__(self, user, fname):
        self.q = TCP_Queue(self.msghandler, closehandler=self.queue_closed)
        self.user = user
        self.f = None
        self.fname = fname
        self.name = os.path.basename(fname)
        self.ui = None
        self.initstate = True
        self.pos = 0
        self.flen = None

    def queue_closed(self, q, parameter, msg):
        if self.f != None:
            self.f.close()
            self.f = None
        if self.ui != None:
            self.ui.cleanup('End')
            self.ui = None
        if self.flen != None and self.pos < self.flen:
            notify('Unable to send a file to %s: %s' % (self.user.get('nick'), self.name), True)
        self.flen = None

    def begin(self):
        try:
            self.f = open(self.fname, 'r')
        except IOError, (errno, strerror):
            self.q.close(TCPQ_ERROR, msg=strerror)
            return False

        try:
            self.f.seek(0, os.SEEK_END)
        except IOError, (errno, strerror):
            self.q.close(TCPQ_ERROR, msg=strerror)
            return False

        self.flen = self.f.tell()
        self.f.seek(0)

        notify('Sending a file to %s: %s (%s)' % (self.user.get('nick'), self.name, format_bytes(self.flen)))

        filetransfer = get_plugin_by_type(PLUGIN_TYPE_FILE_TRANSFER)
        if filetransfer != None:
            title = 'Sending to %s: %s' % (self.user.get('nick'), self.name)
            self.ui = filetransfer.add_transfer(title, self.flen, self.abort_cb)

        return self.connect()

    def abort_cb(self, ctx):
        self.q.close(msg='Aborted')

    def connect(self):
        ip = self.user.get('ip')
        port = self.user.get('port')
        if ip == None or port == None or not self.q.connect((ip, port), TP_CONNECT_TIMEOUT):
            return False

        prefix = TP_SEND_FILE + '\n'
        self.q.write(prefix, writelength = False)

        myuid = community.get_myuid()
        req = {'uid': myuid, 'flen': self.flen, 'name': self.name}
        self.q.write(bencode(req))

        # Close queue that is idle for a period of time
        self.q.set_timeout(ACCEPT_TIMEOUT)

        return True

    def msghandler(self, q, data, parameter):
        if not self.initstate:
            warning('send file: protocol violation!\n')
            return False

        self.initstate = False

        if data == SEND_FILE_ACCEPT:
            self.q.set_timeout(TP_CONNECT_TIMEOUT)

            self.q.set_send_handler(self.send)
            return True
        elif data == SEND_FILE_DENY:
            return False

        warning('send file: invalid message %s\n' % data)
        return False

    def send(self):
        amount = min(TP_MAX_TRANSFER * 4, self.flen - self.pos)

        try:
            chunk = self.f.read(amount)
        except IOError, (errno, strerror):
            self.q.close(TCPQ_ERROR, msg=strerror)
            return None

        self.pos += amount

        if self.ui != None:
            self.ui.update(amount)

        if self.pos == self.flen:
            notify('Sent a file to %s succefully: %s' % (self.user.get('nick'), self.name))
            self.q.set_send_handler(None)
            self.q.close_after_send('Complete')

        return chunk

class Send_File_Plugin(Plugin):
    def __init__(self):
        global sendfile
        self.register_plugin(PLUGIN_TYPE_SEND_FILE)
        self.register_server(TP_SEND_FILE, Send_File_Server)
        sendfile = self
        self.receive_cb = []

    def ready(self):
        global community, notify
        community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        notify = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION).notify

    def send(self, user, fname):
        s = Send_File(user, fname)
        return s.begin()

def init(options):
    Send_File_Plugin()
