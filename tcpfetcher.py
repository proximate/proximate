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
from random import choice

from ioutils import TCP_Queue, TCPQ_NO_CONNECTION
from plugins import Plugin, get_plugin_by_type
from support import debug, warning
from proximateprotocol import TP_FETCH_RECORDS, TP_CONNECT_TIMEOUT, \
     PLUGIN_TYPE_FETCHER, PLUGIN_TYPE_TCP_FETCHER, PLUGIN_TYPE_COMMUNITY, \
     TP_FETCH_TIMEOUT

MAX_QUEUES_PER_USER = 8

community = None
fetcher = None

firstmsg = None

fetchqueues = {}

def select_queue(user):
    # Choose the queue by random, or create a new one if none exists
    uqueues = fetchqueues.get(user)
    if uqueues != None and len(uqueues) > 0:
        return choice(uqueues)
    else:
        return Fetch_Queue(user)

class Fetch_Queue:
    def __init__(self, user=None, sock=None, address=None, data=None):
        self.q = TCP_Queue(self.fetchhandler, closehandler=self.queue_closed)
        self.user = user
        self.openingconnection = (user != None)
        self.reqs = {}
        if self.openingconnection:
            # It's an outgoing queue
            self.add_connection(user)
        else:
            # It's an incoming queue
            self.q.set_timeout(TP_FETCH_TIMEOUT)
            self.q.remote = address
            self.q.append_input(data)
            self.q.initialize(sock)

    def add(self, req):
        # fetch master: start connection process, if necessary
        if self.q.status == TCPQ_NO_CONNECTION and not self.connect():
            return False
        if req.rid >= 0:
            self.reqs[req.rid] = req
        self.q.write(req.payload)
        return True

    def add_connection(self, user):
        queuelist = fetchqueues.setdefault(user, [])
        queuelist.append(self)
        return queuelist

    def cleanup(self, msg):
        if self.user == None:
            return
        queuelist = fetchqueues.get(self.user)
        try:
            queuelist.remove(self)
        except ValueError:
            pass
        debug('fetcher: connection to %s closed: %s\n' % (self.user.tag(), msg))

    def close(self, msg):
        self.q.close(msg=msg)

    def connect(self):
        ip = self.user.get('ip')
        port = self.user.get('port')

        if not community.get_network_state(community.IP_NETWORK):
            # Act as if we were missing the IP network
            warning('fetcher: IP network disabled\n')
            ip = None

        if ip == None or port == None:
            warning('fetcher: No ip/port to open %s\n' % (self.user.tag()))
            return False

        debug('fetcher: open from %s: %s:%s\n' % (self.user.tag(), ip, port))

        if self.openingconnection == False or self.q.connect((ip, port), TP_CONNECT_TIMEOUT) == False:
            return False

        # The first write is seen by opposite side's RPC hander, not TCP_Queue
        prefix = '%s\n' %(TP_FETCH_RECORDS)
        self.q.write(prefix, writelength=False)

        self.q.write(fetcher.encode(firstmsg, -1, ''))

        # Close queue that is idle for a period of time. This is also the
        # maximum processing time for pending requests. Requests taking
        # longer than this must use other state tracking mechanisms.
        self.q.set_timeout(TP_FETCH_TIMEOUT)
        return True

    def fetchhandler(self, q, msg, parameter):
        d = fetcher.decode(msg)
        if d == None:
            warning('fetch master: spurious msg\n')
            return False

        if self.user == None:
            uid = d.get('uid')
            if uid == None or type(uid) != str:
                warning('fetch slave: no uid in fetch connection\n')
                return False
            self.user = community.safe_get_user(uid, q.remote[0])
            if self.user == None:
                warning('fetch slave: Invalid uid from master: %s\n' % (uid))
                return False
            queuelist = self.add_connection(self.user)
            if len(queuelist) > MAX_QUEUES_PER_USER:
                warning('Not allowing too many connections from the same user: %s\n' % (self.user.tag()))
                return False
            debug('fetcher: connection from %s\n' % (self.user.tag()))
            return True

        if len(d['rt']) == 0:
            self.reqs.pop(d['rid'], None)  # Remove pending req (master side)

        fetcher.handle_msg(self.user, d)
        return True

    def queue_closed(self, q, parameter, msg):
        """ Master side: this is called from TCP_Queue close() """

        if self.user == None:
            self.cleanup('No user context -> nothing to retry')
            return

        pendingreqs = []
        for req in self.reqs.values():
            if req.userreplies.has_key(self.user) == False:
                pendingreqs.append(req)

        if len(pendingreqs) == 0:
            self.cleanup('Nothing to retry')
            return

        # First, remove this queue by calling cleanup()
        self.cleanup('Migrate requests')

        # Check requests that can still be resent. Put resendable requests
        # into other queues. Note, this queue is already removed by cleanup().
        q = select_queue(self.user)
        for req in pendingreqs:
            if not req.retry() or not q.add(req):
                req.call(self.user, None)

    def send_reply(self, payload):
        # fetch slave: reply, but connect first, if necessary
        if self.q.status == TCPQ_NO_CONNECTION and not self.connect():
            return False
        self.q.write(payload)
        return True

class TCP_Fetcher(Plugin):
    def __init__(self):
        self.register_plugin(PLUGIN_TYPE_TCP_FETCHER)
        self.register_server(TP_FETCH_RECORDS, Fetch_Queue)
        self.efficient_fetch_community = False

    def fetch_community(self, com, rtype, request, callback, ctx, retries, ack):
        # Try to connect to every user individually.
        # Note, myself is not considered an active user.
        for user in community.get_community_members(com):
            fetcher.fetch(user, rtype, request, callback, ctx=ctx, retries=retries, ack=ack)
        return True

    def functional(self):
        return True

    def ready(self):
        global community, fetcher, firstmsg

        community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        fetcher = get_plugin_by_type(PLUGIN_TYPE_FETCHER)

        # First record is my uid. 't' and 'rt' are just filled in
        # because they are checked on the slave side.
        firstmsg = {'t': '', 'uid': community.get_myuid(), 'c': ''}

    def send_request(self, user, req):
        return select_queue(user).add(req)

    def send_reply(self, user, rid, payload):
        if not select_queue(user).send_reply(payload):
            warning('fetcher: Can not reply to rid %d for %s\n' % (rid, user.tag()))

def init(options):
    TCP_Fetcher()
