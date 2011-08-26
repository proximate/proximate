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
from errno import EAGAIN, EINTR
from gobject import io_add_watch, timeout_add, IO_IN, source_remove
import zlib
from random import random
from typevalidator import validate, ONE_OR_MORE

from meta import is_unsigned_int
from ioutils import create_udp_socket, send_broadcast
from plugins import Plugin, get_plugin_by_type
from support import info, warning, debug
from proximateprotocol import PLUGIN_TYPE_UDP_FETCHER, PLUGIN_TYPE_FETCHER, \
     PLUGIN_TYPE_COMMUNITY, valid_uid, TP_MAX_RECORD_SIZE
from fetcher import Request
from bencode import fmt_bdecode, bencode
from utils import decompress_with_limit

MTU = 1024

RETRY_INTERVAL = 10  # sec
MAX_RETRIES = 3
SEND_ACK_DELAY = 2 # sec
RECEIVE_TIMEOUT = 40  # sec

PACKET_DATA = 'data'
PACKET_ACK = 'ack'

pending_sends = {}
pending_receives = {}
community = None
plugin = None

class UDP_Sender:
    def __init__(self, user, packet, fragments, retries, first=True, ack=False):
        self.user = user
        self.packet = packet   # Packet identifier number
        self.fragments = fragments # Fragments that are not yet acked
        self.fragcount = len(fragments)
        self.retries = retries
        self.ack = ack

        if first:
            self.send_fragments()

        self.retrytag = timeout_add(RETRY_INTERVAL * 1000, self.retry_timer)

    def cleanup(self, success):
        if self.retrytag != None:
            source_remove(self.retrytag)
            self.retrytag = None

    def send_fragments(self):
        debug('%d send frag %s\n' % (self.packet, str(self.fragments.keys())))
        for frag, data in self.fragments.items():
            plugin.send_lowlevel(self.user, data)

    def retry_timer(self):
        if self.retries == 0:
            self.cleanup(False)
            return False

        self.send_fragments()

        self.retries -= 1
        return True

class UDP_Sender_With_Ack(UDP_Sender):
    def __init__(self, user, packet, fragments, retries, cb, ctx, first=True):
        UDP_Sender.__init__(self, user, packet, fragments, retries, first, True)
        self.cb = cb
        self.ctx = ctx

        key = (self.user, self.packet)
        global pending_sends
        pending_sends[key] = self

    def cleanup(self, success):
        global pending_sends

        key = (self.user, self.packet)
        pending_sends.pop(key)

        if self.cb != None:
            self.cb(self.user, self.ctx, success)

        UDP_Sender.cleanup(self, success)

    def handle_ack(self, d):
        for frag in d['ack']:
            if frag in self.fragments:
                debug('%d acked %d\n' % (self.packet, frag))
                self.fragments.pop(frag)

        if len(self.fragments) == 0:    # All fragments acked
            debug('%d sent!\n' % (self.packet))
            self.cleanup(True)

class UDP_Receiver:
    def __init__(self, user, packet):
        self.user = user
        self.packet = packet      # Packet identifier number
        self.fragments = {}
        self.fragcount = None
        self.ack = True
        self.acktag = None

        self.timeouttag = timeout_add(RECEIVE_TIMEOUT * 1000, self.timeout)

        key = (self.user, self.packet)
        global pending_receives
        pending_receives[key] = self

    def remove_delayed_ack(self):
        if self.acktag != None:
            source_remove(self.acktag)
            self.acktag = None

    def timeout(self):
        global pending_receives

        key = (self.user, self.packet)
        pending_receives.pop(key)
        self.remove_delayed_ack()
        return False

    def delayed_ack(self):
        self.acktag = None
        self.send_ack()
        return False

    def send_ack(self):
        debug('%d send ack %s\n' % (self.packet, str(self.fragments.keys())))
        data = bencode({
            't': PACKET_ACK,
            'from': community.get_myuid(),
            'to': self.user.get('uid'),
            'packet': self.packet,
            'ack': self.fragments.keys()
            })
        plugin.send_lowlevel(self.user, data)

    def handle_data(self, d):
        frag = d['frag']      # Fragment number
        if self.fragcount == None:
            self.fragcount = d['fragcount']
            self.ack = d['ack']
        elif self.fragcount != d['fragcount']:
            warning('Invalid number of fragments %d\n' % d['fragcount'])
            return
        if frag >= self.fragcount:
            warning('Invalid fragment %d\n' % (frag))
            return

        # Start timer to receive more fragments before sending the ack
        if self.acktag == None and self.ack:
            self.acktag = timeout_add(SEND_ACK_DELAY * 1000, self.delayed_ack)

        if frag in self.fragments:     # Already received
            debug('%d duplicate %d\n' % (self.packet, frag))
            return
        self.fragments[frag] = d['payload']
        debug('%d recv %d\n' % (self.packet, frag))

        if len(self.fragments) == self.fragcount:
            # All fragments received. Send ack instantly.
            debug('%d received!\n' % (self.packet))
            self.remove_delayed_ack()
            if self.ack:
                self.send_ack()

            payload = ''
            for frag in range(self.fragcount):
                payload += self.fragments[frag]

            plugin.handle_packet(self.user, payload)

        # Restart timeout
        source_remove(self.timeouttag)
        self.timeouttag = timeout_add(RECEIVE_TIMEOUT * 1000, self.timeout)


class UDP_Fetcher(Plugin):
    packetspec = {
        't': str,
        'from': valid_uid,
        'to': str,
        }

    def __init__(self, options):
        if not options.udp_fetcher:
            return

        self.register_plugin(PLUGIN_TYPE_UDP_FETCHER)
        self.fetcher = None
        self.packet = 0
        self.efficient_fetch_community = False
        self.packetloss = 0.0

        self.handlers = {
            PACKET_DATA: self.got_data,
            PACKET_ACK: self.got_ack,
        }

    def functional(self):
        return True

    def ready(self):
        global community, plugin
        community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        self.fetcher = get_plugin_by_type(PLUGIN_TYPE_FETCHER)
        plugin = self

        self.create_udp_listener()

    def create_udp_listener(self):
        port = community.get_rpc_port()
        info('fetcher: Listening to UDP port %d\n' % port)
        rfd = create_udp_socket('', port, False, reuse = True)
        if rfd == None:
            warning('Can not listen to UDP broadcasts\n')
            return

        rfd.setblocking(False)
        io_add_watch(rfd, IO_IN, self.udp_listener_read)

    def udp_listener_read(self, rfd, condition):
        try:
            data, address = rfd.recvfrom(2048)
        except socket.error, (errno, strerror):
            ret = (errno == EAGAIN or errno == EINTR)
            if not ret:
                warning('Socket error (%s): %s\n' % (errno, strerror))
            return ret

        if self.packetloss > 0.0 and random() < self.packetloss:
            return True

        d = fmt_bdecode(self.packetspec, data)
        if d == None:
            warning('fetcher: Received an invalid packet: %s\n' % data)
            return

        if d['from'] == community.get_myuid():   # Received own packet
            return
        if d['to'] != community.get_myuid():    # Packet not for me
            return

        user = community.get_user(d['from'])
        if user == None:
            warning('fetcher: Packet from invalid uid %s\n' % (d['from']))
            return

        handler = self.handlers.get(d['t'])
        if handler == None:
            warning('fetcher: Invalid packet type: %s\n' % (d['t']))
            return

        handler(user, d)
        return True

    def got_data(self, user, d):
        validator = {
            'packet': int,
            'frag': lambda i: is_unsigned_int('frag', i),
            'fragcount': lambda i: is_unsigned_int('fragcount', i),
            'payload': str,
            'ack': bool,
        }
        if not validate(validator, d):
            warning('fetcher: Invalid data packet %s\n' % str(d))
            return

        if d['fragcount'] > TP_MAX_RECORD_SIZE // MTU + 1:
            warning('fetcher: Too large packet %d\n' % d['fragcount'])
            return
        if len(d['payload']) > MTU * 2:
            warning('fetcher: Received too large fragment %d\n' % len(d['payload']))
            return

        key = (user, d['packet'])
        o = pending_receives.get(key)
        if o == None:
            # We have not yet received any fragments from this packet
            o = UDP_Receiver(user, d['packet'])

        o.handle_data(d)

    def got_ack(self, user, d):
        validator = {
            'packet': int,
            'ack': [ONE_OR_MORE, lambda i: is_unsigned_int('ack', i)],
        }
        if not validate(validator, d):
            warning('fetcher: Invalid ack packet %s\n' % str(d))
            return

        key = (user, d['packet'])
        o = pending_sends.get(key)
        if o != None:
            o.handle_ack(d)

    def send_lowlevel(self, user, data):
        ip = user.get('ip')
        port = user.get('port')
        if ip == None or port == None:
            warning('fetcher: No ip/port to open %s\n' % (user.tag()))
            return
        send_broadcast(ip, port, data)

    def send_packet(self, user, payload, cb, ctx=None, ack=True):
        payload = zlib.compress(payload)

        fragcount = (len(payload) + (MTU - 1)) // MTU
        fragments = {}
        for frag in range(fragcount):
            fragments[frag] = bencode({
                't': PACKET_DATA,
                'from': community.get_myuid(),
                'to': user.get('uid'),
                'packet': self.packet,
                'frag': frag,
                'fragcount': fragcount,
                'payload': payload[frag * MTU:frag * MTU + MTU],
                'ack': ack
                })

        if ack:
            UDP_Sender_With_Ack(user, self.packet, fragments, MAX_RETRIES, cb, ctx)
        else:
            # send the packet twice
            UDP_Sender(user, self.packet, fragments, 1)

        self.packet += 1

    def handle_packet(self, user, payload):
        dec = decompress_with_limit(payload, TP_MAX_RECORD_SIZE)
        if dec == None:
            # The message is corrupt or not compressed. Decode anyway.
            dec = payload

        msg = self.fetcher.decode(dec)
        if msg == None:
            return

        if community.is_blacklisted(user):
            return

        self.fetcher.handle_msg(user, msg)

    def fetch_community(self, com, rtype, request, callback, ctx, retries, ack):
        # Try to connect to every user individually.
        # Note, myself is not considered an active user.
        for user in community.get_community_members(com):
            self.fetcher.fetch(user, rtype, request, callback, ctx=ctx, retries=retries, ack=ack)
        return True

    def send_request(self, user, req):
        ack = (req.rid >= 0)
        self.send_packet(user, req.payload, self.fetch_cb, req, ack)
        return True

    def fetch_cb(self, user, req, success):
        if success:
            return

        if req.retry():
            debug('Retrying fetch to %s\n' % user.tag())
            self.fetch(user, req)
        else:
            req.call(user, None)

    def send_reply(self, user, rid, payload):
        self.send_packet(user, payload, None)

def init(options):
    UDP_Fetcher(options)
