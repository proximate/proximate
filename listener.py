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
Listen for incoming TCP connections
"""
from errno import EAGAIN, EINTR
from gobject import io_add_watch, source_remove, timeout_add, IO_IN
import socket

from ioutils import create_tcp_listener
from plugins import rpc_commands, get_plugin_by_type
from support import debug, warning, info
from proximateprotocol import TP_PROTOCOL_TIMEOUT, TP_MAX_CMD_NAME_LEN, \
     RPC_MORE_DATA, RPC_CLOSE, RPC_RELEASE, PORT_RETRIES, DEFAULT_PROXIMATE_PORT, \
     PLUGIN_TYPE_COMMUNITY

community = None

listener = None

class Connection:
    def __init__(self, sock, address):
        # Act like the IP network does not exist
        if not community.get_network_state(community.IP_NETWORK):
            return

        self.sock = sock
        self.address = address
        self.data = []
        self.nbytes = 0
        # Put self reference to avoid garbage collection
        self.iotag = io_add_watch(sock, IO_IN, self.read, self)
        self.timeouttag = timeout_add(TP_PROTOCOL_TIMEOUT * 1000, self.close)

    def remove_io_notifications(self):
        if self.iotag != None:
            source_remove(self.iotag)
            self.iotag = None
        if self.timeouttag != None:
            source_remove(self.timeouttag)
            self.timeouttag = None

    def close(self):
        self.remove_io_notifications()
        self.sock.close()
        self.sock = None
        return False

    def handle_rpc_message(self, data, eof):
        if len(data) == 0:
            self.close()
            return False

        cmd = data[0:TP_MAX_CMD_NAME_LEN].split('\n')[0]

        rpchandler = rpc_commands.get(cmd)
        if rpchandler == None:
            self.close()
            return False

        payload = data[(len(cmd) + 1):]

        status = rpchandler(cmd, payload, eof, self.sock, self.address)
        ret = False
        if status == RPC_MORE_DATA:
            ret = True
        elif status == RPC_CLOSE:
            self.close()
        elif status == RPC_RELEASE:
            # We are not interested to gobject events anymore
            self.remove_io_notifications()
        else:
            self.close()
            warning('Unknown RPC value: %s\n' %(str(status)))
        return ret

    def read(self, fd, condition, this):
        try:
            chunk = self.sock.recv(4096)
        except socket.error, (errno, strerror):
            ret = (errno == EAGAIN or errno == EINTR)
            if not ret:
                warning('Listener: Read error (%s): %s\n' %(errno, strerror))
                self.close()
            return ret

        self.nbytes += len(chunk)
        self.data.append(chunk)

        gotfirstline = (chunk.find('\n') >= 0)
        eof = (len(chunk) == 0)

        ret = True
        if eof or self.nbytes > TP_MAX_CMD_NAME_LEN or gotfirstline:
            # Data compaction
            data = ''.join(self.data)
            self.data = [data]

            # The handler may take control over the socket (return False)
            ret = self.handle_rpc_message(data, eof)

        return ret

def tcp_listener_accept(rfd, conditions):
    try:
        (sock, address) = rfd.accept()
    except socket.error, (errno, strerror):
        ret = (errno == EAGAIN or errno == EINTR)
        if not ret:
            warning('Listener: Socket error (%s): %s\n' % (errno, strerror))
        return ret

    sock.setblocking(False)

    Connection(sock, address)
    return True

def init():
    """ Bind a default and a random port.
        The random port is used for local network communication.
        The default port is used to establish remote connections. """

    global community
    community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)

    create_tcp_listener(DEFAULT_PROXIMATE_PORT, tcp_listener_accept, reuse=True)

    success = False
    for i in xrange(PORT_RETRIES):
        port = community.get_rpc_port()
        if port == DEFAULT_PROXIMATE_PORT:
            continue
        (rfd, tag) = create_tcp_listener(port, tcp_listener_accept, reuse=True)
        if rfd != None:
            info('Listening to TCP connections on port %d\n' %(port))
            success = True
            break
        warning('Can not bind to TCP port %d\n' %(port))
        # Generate a new port number so that next iteration will not fail
        if not community.gen_port():
            break

    if not success:
        warning('Can not listen to TCP connections\n')
