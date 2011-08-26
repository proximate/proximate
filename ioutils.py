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
from gobject import io_add_watch, timeout_add, source_remove, IO_IN, IO_OUT, \
     PRIORITY_LOW
from os import SEEK_END
from socket import AF_INET, SOCK_DGRAM, SOCK_STREAM, SOL_SOCKET, \
     SO_BROADCAST, SO_ERROR, SO_REUSEADDR, socket, error, herror, gaierror, \
     inet_ntoa, inet_aton
from errno import EAGAIN, EINPROGRESS, EINTR, EADDRNOTAVAIL
import fcntl
import struct
import os

from support import debug, die, warning
from proximateprotocol import TP_MAX_TRANSFER, TP_MAX_RECORD_SIZE
from utils import str_to_int
from plugins import get_plugin_by_type

TCPQ_NO_CONNECTION = 0
TCPQ_OK = 1
TCPQ_EOF = 2
TCPQ_CONNECTION_TIMEOUT = 3
TCPQ_CONNECTION_REFUSED = 4
TCPQ_UNKNOWN_HOST = 5
TCPQ_TIMEOUT = 6
TCPQ_PROTOCOL_VIOLATION = 7
TCPQ_CONNECTING = 8
TCPQ_ERROR = 9

def bind_socket(sock, address, port):
    try:
        sock.bind((address, port))
    except error, (errno, strerror):
        return False
    except herror, (errno, strerror):
        return False
    except gaierror, (errno, strerror):
        return False

    return True

def connect_socket(sock, name, port):
    while True:
        try:
            sock.connect((name, port))
        except error, (errno, strerror):
            # 1. Connection now in progress (EINPROGRESS)
            # 2. Connection refused (ECONNREFUSED)
            debug('connect_socket: %s %d: %s\n' %(name, port, strerror))
            if errno == EINTR:
                continue
            return errno == EINPROGRESS
        except gaierror, (errno, strerror):
            # Unknown host name
            debug('connect_socket: %s %d: %s\n' %(name, port, strerror))
            return False
        break
    return True

def create_tcp_socket(address, port, reuse = False):
    """ If port != 0, create and bind listening socket on the given
    port and address. Otherwise create a socket that can be connected.

    Returns the socket when successful, otherwise None."""

    try:
        sock = socket(AF_INET, SOCK_STREAM)
    except error, (errno, strerror):
        debug('ioutils error (%s): %s\n' %(errno, strerror))
        return None

    if reuse:
        sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)

    if port != 0:
        if not bind_socket(sock, address, port):
            debug('ioutils: Can not bind\n')
            return None

        sock.listen(5)

    return sock

def create_tcp_listener(port, accepthandler, reuse = False):
    rfd = create_tcp_socket('', port, reuse = reuse)
    if rfd == None:
        return (None, None)
    rfd.setblocking(False)
    tag = io_add_watch(rfd, IO_IN, accepthandler)
    return (rfd, tag)

def filesize(path):
    try:
        size = os.path.getsize(path)
    except OSError:
        return 0
    return size

def get_flen(f):
    error = None
    try:
        f.seek(0, SEEK_END)
        flen = f.tell()
        f.seek(0)
    except IOError, (errno, strerror):
        # Some files are not seekable
        flen = 0
        error = 'Can not seek file %s: %s' %(fname, strerror)
    return (flen, error)

def get_ip_address(ifname):
    fail = (None, None)
    no_conn = ('', None)

    try:
        sock = socket(AF_INET, SOCK_STREAM)
    except error, (errno, strerror):
        debug('ioutils error (%s): %s\n' %(errno, strerror))
        return fail

    try:
        ip = fcntl.ioctl(sock.fileno(), 0x8915, struct.pack('256s', ifname[:15]))[20:24]
        bcast = fcntl.ioctl(sock.fileno(), 0x8919, struct.pack('256s', ifname[:15]))[20:24]
    except IOError, (errno, strerror):
        if errno == EADDRNOTAVAIL:
            return no_conn
        return fail

    sock.close()

    return (inet_ntoa(ip), inet_ntoa(bcast))

def create_udp_socket(address, port, bcast, reuse = False):
    """ If port != 0, create and bind listening socket on port
    and address. If bcast == True, create a broadcast socket.

    Returns the socket when successful, otherwise None."""

    if port != 0 and bcast:
        debug('create_udp_socket: both port != 0 and bcast == True may not be true\n')
        return None

    try:
        sock = socket(AF_INET, SOCK_DGRAM)
    except error, (errno, strerror):
        debug('ioutils error (%s): %s\n' %(errno, strerror))
        return None

    if reuse:
        sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)

    if port != 0:
        if not bind_socket(sock, address, port):
            debug('ioutils: Can not bind\n')
            return None
    elif bcast:
        try:
            sock.setsockopt(SOL_SOCKET, SO_BROADCAST, True)
        except error, (errno, strerror):
            debug('ioutils error (%s): %s\n' %(errno, strerror))
            return None

    return sock

def send_broadcast(address, bcast_port, msg):
    """ Send an UDP broadcast message. """

    bcast_sock = create_udp_socket('', 0, True)
    if bcast_sock == None:
        warning('Can not create UDP socket: unable to broadcast\n')
        return 0

    bcast_sock.setblocking(False)

    try:
        bytes_sent = bcast_sock.sendto(msg, (address, bcast_port))
    except error, (errno, strerror):
        warning('Error sending broadcast to (%s, %d): %s\n' %(address, bcast_port, strerror))
        return errno

    if bytes_sent != len(msg):
        warning('Error sending broadcast: only %d bytes sent\n' %(bytes_sent))
        return EAGAIN

    return 0

def valid_ip(ip):
    try:
        a = inet_aton(ip)
    except error, (errno, strerror):
        return False
    return True

class TCP_Queue:
    """ TCP_Queue is a bidirectional messaging class for TCP sockets.
    Messages are read as sequential records from the pipe. Messages
    can also be written to the pipe. Messages are not passed to handler
    until whole record is received.
    """

    initialized = False

    def __init__(self, handler, parameter = None, closehandler = None):
        self.handler = handler
        self.parameter = parameter
        self.closehandler = closehandler
        self.status = TCPQ_NO_CONNECTION

        self.sock = None
        self.rtag = None
        self.wtag = None
        self.timeouttag = None
        self.connecttimeouttag = None
        self.throttled = False

        self.timeinterval = None
        self.maxsize = TP_MAX_RECORD_SIZE
        self.wsize = TP_MAX_TRANSFER

        self.bytestransferred = 0
        self.timeoutbytes = 1

        self.inb = ''
        self.outb = ''
        self.msglen = None

        self.recv_handler = None
        self.send_handler = None

        self.closeaftersend = None

    def connect(self, address, timeout = None):
        assert(self.status != TCPQ_OK)

        self.sock = create_tcp_socket('', 0)
        if self.sock == None:
            return False

        self.sock.setblocking(False)

        if not connect_socket(self.sock, address[0], address[1]):
            self.close(TCPQ_UNKNOWN_HOST, 'Unknown host')
            return False

        self.status = TCPQ_CONNECTING

        self.wtag = io_add_watch(self.sock, IO_OUT, self.check_connect)
        if timeout != None:
            self.connecttimeouttag = timeout_add(timeout * 1000, self.no_connection)

        return True

    def no_connection(self):
        self.close(TCPQ_CONNECTION_TIMEOUT, 'Connection timeout')
        return False

    def check_connect(self, fd, condition):
        if self.sock.getsockopt(SOL_SOCKET, SO_ERROR) != 0:
            self.close(TCPQ_CONNECTION_REFUSED, 'Connection refused')
        else:
            # Stop waiting for write, which was meant for connect()
            self.writemode(False)
            # Remove connection timeout
            self.remove_connection_timeout()

            self.initialize(self.sock)

        return False

    def initialize(self, sock):
        """ Called when connection is estabilished. """

        assert(self.status != TCPQ_OK)
        self.sock = sock
        self.bytestransferred = 0

        self.status = TCPQ_OK

        if not self.throttled:
            self.readmode()

        if len(self.inb) > 0:
            self.process()

        # Enable write mode if required
        if len(self.outb) > 0 or self.send_handler != None:
            self.writemode()

    def append_input(self, data):
        """ This function can be used to insert arbitrary data to the
        input queue. It is useful when the socket has already been read before
        creating TCP_Queue object. The data that was read can be partially
        or fully passed for TCP_Queue to be processed. This can be used
        to skip protocol headers before processing the connection as
        TCP_Queue messages. """

        if self.status == TCPQ_OK:
            die('TCP_Queue: you may not insert data with append_input() after it has been initialized!\n')

        self.inb += data

    def set_close_handler(self, f):
        self.closehandler = f

    def set_timeout(self, timeinterval, timeoutbytes = 1):
        """ Set or remove timeout. Timeout is removed if timeinterval == None.
        Otherwise the timeout in seconds is 'timeinterval'. During this
        interval at least 'timeoutbytes' must be transferred in total to
        either direction. By default 'timeoutbytes' is 1, which means that if
        any IO takes place within 'timeinterval' seconds, the connection does
        not timeout. """

        self.remove_data_timeout()
        if timeinterval == None:
            return
        assert(timeinterval > 0 and timeoutbytes > 0)
        self.timeoutbytes = timeoutbytes
        self.timeouttag = timeout_add(timeinterval * 1000, self.timeout)

    def set_max_message_size(self, maxsize):
        assert(maxsize == None or maxsize > 0)
        self.maxsize = maxsize

    def set_wsize(self, wsize):
        assert(wsize > 0)
        self.wsize = wsize

    def set_send_handler(self, handler = None):
        """ Start streaming mode. Given handler is called when output queue
            is to be filled. Handler can report error by calling close() and
            returning None.

            Setting None ends streaming mode. """

        self.send_handler = handler

        # If we do not currently in send mode, make sure we start writing to
        # the socket by enabling the write watch.
        # NOTE: The write watch is disabled inside the write handler when
        # it is no longer needed.
        if handler != None:
            self.writemode()

    def set_recv_handler(self, handler = None):
        """ Set handler for incoming data. Can be used for receiving streaming
            data. Handler should return number of bytes it consumed.

            Handler can report error by calling close() and returning None.

            Setting handler to None will return to normal operation. """

        self.recv_handler = handler

    def throttle(self, enabled = True):
        """ Start or stop throttling received data. """

        self.throttled = enabled

        # If we are leaving the throttled mode, make sure the read watch
        # is installed and we are reading data from the socket.
        if not enabled:
            self.readmode()

    def readmode(self, readenable=True):
        """ Enable or disable read event handler. Should not be called from
            the outside of TCP_Queue """

        if readenable:
            if self.rtag == None:
                self.rtag = io_add_watch(self.sock, IO_IN, self.socket_read, priority=PRIORITY_LOW)
        elif self.rtag != None:
            source_remove(self.rtag)
            self.rtag = None

    def writemode(self, writeenable=True):
        """ Enable or disable write event handler. Should not be called from
            the outside of TCP_Queue """

        if writeenable:
            if self.wtag == None:
                self.wtag = io_add_watch(self.sock, IO_OUT, self.socket_write, priority=PRIORITY_LOW)
        elif self.wtag != None:
            source_remove(self.wtag)
            self.wtag = None

    def remove_connection_timeout(self):
        if self.connecttimeouttag != None:
            source_remove(self.connecttimeouttag)
            self.connecttimeouttag = None

    def remove_data_timeout(self):
        if self.timeouttag != None:
            source_remove(self.timeouttag)
            self.timeouttag = None

    def remove_io_notifications(self):
        self.readmode(False)
        self.writemode(False)
        self.remove_data_timeout()
        self.remove_connection_timeout()

    def close(self, status = TCPQ_EOF, msg = ''):
        debug('TCP_Queue closed: status %d (%s)\n' %(status, msg))
        self.inb = ''
        self.outb = ''
        self.send_handler = None
        self.recv_handler = None
        self.throttled = False
        self.status = status
        self.remove_io_notifications()

        if self.sock != None:
            self.sock.close()
            self.sock = None

        if self.closehandler != None:
            self.closehandler(self, self.parameter, msg)

    def close_after_send(self, msg=''):
        self.closeaftersend = msg
        self.writemode()

    def timeout(self):
        if self.bytestransferred < self.timeoutbytes:
            self.close(TCPQ_TIMEOUT, 'Idle timeout')
            return False
        self.bytestransferred = 0
        return True

    def get_one_msg(self):
        """ Messages come in formatted as: LENGTH1 + MSG1 + LENGTH2 + MSG2 + ..

        where LENGTHx is a bencoded unsigned integer, e.g. 'i65e' == 65 bytes.
        The actual message comes directly after length. The message is
        arbitrary binary data.

        self.msglen is used to store the length of a message that is currently
        being read.

        The function has two states:

        1. self.msglen == None
           * read LENGTH-X
        2. self.msglen >= 0
           * read MSG-X
        """

        nothing = (True, None)
        error = (False, None)

        if self.msglen == None:
            # Read bencoded unsigned integer. We don't actually need to check
            # the initial prefix character 'i'.
            i = self.inb.find('e')
            if i < 0:
                if len(self.inb) < 10:
                    return nothing
                # Too long a header without a terminator, kill connection
                return error
            try:
                x = int(self.inb[1:i])
            except ValueError:
                x = -1
            if x < 0 or (self.maxsize != None and x > self.maxsize):
                return error
            self.msglen = x
            self.inb = self.inb[(i + 1):]

        if self.msglen == None or len(self.inb) < self.msglen:
            return nothing

        # We got the full payload
        # Remove the payload from the beginning of self.inb and return it
        msg = self.inb[0:self.msglen]
        self.inb = self.inb[self.msglen:]

        # Next time: read a message length (don't come here)
        self.msglen = None

        return (True, msg)

    def process(self):
        """ Process all complete and valid messages in self.inb """

        assert(self.status == TCPQ_OK)

        success = True
        status = TCPQ_PROTOCOL_VIOLATION

        # Note: throttling can be enabled inside handler
        while success and not self.throttled:
            # In streaming mode, give all received data to handler
            if self.recv_handler != None:
                consumed = self.recv_handler(self.inb)
                if consumed == None:
                    return False
                self.inb = self.inb[consumed:]
                if len(self.inb) == 0:
                    break
            else:
                (success, msg) = self.get_one_msg()
                if msg == None:
                    break
                success = self.handler(self, msg, self.parameter)

        if not success:
            self.close(status)

        return success

    def socket_read(self, fd, condition):
        """ Received data is now available on the socket. """

        assert(self.status == TCPQ_OK)

        try:
            chunk = self.sock.recv(TP_MAX_TRANSFER)
        except error, (errno, strerror):
            warning('TCP_Queue read error %d: %s\n' %(errno, strerror))
            ret = (errno == EAGAIN or errno == EINTR)
            if not ret:
                self.close(TCPQ_ERROR, msg = strerror)
            return ret

        if len(chunk) == 0:
            self.close(TCPQ_EOF)
            return False

        self.bytestransferred += len(chunk)
        self.inb += chunk

        if not self.process():
            return False

        # Do we continue in read mode?
        ret = not self.throttled
        if not ret:
            self.readmode(False)
        return ret

    def write_buffer(self):
        """ Write from the send queue to the socket. Maximum amount of written
            data is the window size. """

        chunk = self.outb[0:self.wsize]

        try:
            bytes = self.sock.send(chunk)
        except error, (errno, strerror):
            warning('TCP_Queue send error %d: %s\n' %(errno, strerror))
            ret = (errno == EAGAIN or errno == EINTR)
            if not ret:
                self.close(TCPQ_ERROR, msg = strerror)
            return ret

        # Succefully sent data. Remove from the beginning of self.outb
        self.bytestransferred += bytes
        self.outb = self.outb[bytes:]
        return True

    def socket_write(self, fd, condition):
        """ The socket can be now written to. """

        assert(self.status == TCPQ_OK)

        # If we are sending stream, fill send queue
        if self.send_handler != None and len(self.outb) < self.wsize:
            chunk = self.send_handler()
            if chunk == None:
                return False
            self.outb += chunk

        if not self.write_buffer():
            return False

        if not self.throttled and len(self.inb) > 0:
            # We have possibly have come back from throttled mode, process
            # buffered data
            if not self.process():
                return False

        # Do we continue in write mode?
        ret = len(self.outb) > 0 or self.send_handler != None
        if not ret:
            if self.closeaftersend != None:
                self.close(msg=self.closeaftersend)
            else:
                self.writemode(False)

        return ret

    def write(self, msg, writelength=True):
        """ Write a message to the queue. msg is an arbitrary binary blob
        to be sent.

        Normally, all messages are prefixed with a message length. When one
        sends a message "foo", it is prefixed with bencoded number 3 indicating
        the length of "foo". However, if writelength == False, the length is
        not sent. This can be used for hacks, for example, to prefix a new
        connection with a magic value.

        Note, msg with zero length is actually sent. The other party will
        receive an empty string.
        """

        if writelength:
            self.outb += 'i%de' % len(msg)

        self.outb += msg

        # If we do not currently in send mode, make sure we start writing to
        # the socket by enabling the write watch.
        # NOTE: The write watch is disabled inside the write handler when
        # it is no longer needed.
        if self.status == TCPQ_OK:
            self.writemode()
