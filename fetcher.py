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

from bencode import bencode, fmt_bdecode
from typevalidator import validate, OPTIONAL_KEY
from plugins import Plugin, get_plugin_by_type
from support import debug, die, warning
from proximateprotocol import PLUGIN_TYPE_FETCHER, PLUGIN_TYPE_TCP_FETCHER, \
     PLUGIN_TYPE_COMMUNITY, PLUGIN_TYPE_SCHEDULER, TP_FETCH_TIMEOUT, \
     PLUGIN_TYPE_UDP_FETCHER

RETIREMENT_CYCLE = 5
FETCH_TIMEOUT_STEPS = TP_FETCH_TIMEOUT // RETIREMENT_CYCLE

community = None
fetcher = None

pendingreqs = {}

class Request:
    def __init__(self, rid, payload, callback, ctx, retries):
        self.rid = rid
        self.payload = payload
        self.callback = callback
        self.ctx = ctx
        self.retries = retries
        # +1 because timeout cycle is out of sync with creating the request
        self.ttl = FETCH_TIMEOUT_STEPS + 1
        self.userreplies = {}

    def call(self, user, reply):
        if self.callback != None and self.userreplies.has_key(user) == False:
            self.callback(user, reply, self.ctx)
            self.userreplies[user] = None

        fetcher.get_pending(user, self.rid, pop=True)

    def check_timeout(self, user):
        self.ttl -= 1
        if self.ttl <= 0:
            self.call(user, None)
            return False
        return True

    def retry(self):
        failure = (self.retries > 0)
        self.retries -= 1
        return failure

class Special_Reply:
    pass

class Fetcher_Plugin(Plugin):
    POSTPONE_REPLY = Special_Reply()
    SILENT_COMMUNITY_ERROR = Special_Reply()

    decodespec = {'rid': int, OPTIONAL_KEY('v'): int, 't': str, 'rt': str, 'c': str}

    def __init__(self):
        self.register_plugin(PLUGIN_TYPE_FETCHER)
        self.handlers = {}
        self.handlername = {}
        self.rid = 0

    def close_ip_connections(self, msg):
        for queuelist in fetchqueues.values():
            for fq in queuelist:
                fq.close(msg)

    def decode(self, payload):
        d = fmt_bdecode(self.decodespec, payload)
        if d == None:
            warning('Invalid fetcher payload: %s\n' % payload)
        return d

    def encode(self, msg, rid, rt):
        if type(msg) != dict:
            warning('fetcher: message must be a dictionary: %s\n' %(str(msg)), printstack=True)
            return None
        msg.setdefault('v', 0)
        msg.setdefault('t', '')
        msg['rid'] = rid
        msg['rt'] = rt
        return bencode(msg)

    def fetch(self, user, rtype, request, callback, ctx=None, retries=0, ack=True):
        """ Tries to fetch data from an user.

            user: user to fetch from
            rtype: type of the request, an arbitrary string
            request: message (dictionary) to send to the counter side
            callback: function to be called after data is fetched.
                      gets the return value of the counterparty's
                      handling function and the context as parameters.
                      This parameter can be None.
            ctx: context of the request, an arbitrary object
            retries: number of retries
            ack: If True, reply is expected and a lost message is (possibly)
                 retransmitted according.
        """
        assert(retries >= 0)

        request.setdefault('c', '')

        rid = self.obtain_rid(ack)

        payload = self.encode(request, rid, rtype)
        if payload == None:
            return False

        self.log('fetcher.fetch', user, request, payload)

        req = Request(rid, payload, callback, ctx, retries)

        success = self.backend.send_request(user, req)

        # Add request to the pending queue, unless it is a no-ack request.
        # The request is removed from the queue when req.call() is called.
        if success and rid >= 0:
            self.set_pending([user], req)

        return success

    def fetch_community(self, com, rtype, request, callback, ctx=None, retries=0, ack=True):
        """ Send fetch to every user in given community.

            Because users in communities can appear and disappear at
            any time, we take snapshot of currently active users.
        """

        request['c'] = com.get('name')
        return self.backend.fetch_community(com, rtype, request, callback, ctx=ctx, retries=retries, ack=ack)

    def is_fetch_community_efficient(self):
        return self.backend.efficient_fetch_community

    def log(self, name, user, request, payload):
        d = {'rid': request['rid'],
             'rt': request['rt'],
             't': request.get('t', ''),
             'nfields': len(request),
             'nbytes': len(payload),
            }
        c = request.get('c')
        if c != None:
            d['c'] = c
        if user != None:
            d['uid'] = user.get('uid')

    def fetch_queue_retirement(self, t, ctx):
        for (user, ureqs) in pendingreqs.items():
            for req in ureqs.values():
                req.check_timeout(user)
            if len(ureqs) == 0:
                # Cleanup unused queues to avoid re-scanning in the future
                pendingreqs.pop(user)
        return True

    def obtain_rid(self, ack):
        if ack:
            rid = self.rid
            self.rid += 1
        else:
            rid = -1 # No reply for the request
        return rid

    def ready(self):
        global community, fetcher
        fetcher = self
        community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)

        for p in [PLUGIN_TYPE_UDP_FETCHER, PLUGIN_TYPE_TCP_FETCHER]:
            self.backend = get_plugin_by_type(p)
            if self.backend != None and self.backend.functional():
                break

        sch = get_plugin_by_type(PLUGIN_TYPE_SCHEDULER)
        sch.call_periodic(RETIREMENT_CYCLE * sch.SECOND, self.fetch_queue_retirement)

    def register_handler(self, rtype, handler, handlername):
        """ Register a slave handler that replies to the master.
            Handler will be called with the ip address and the payload
            of the message from master when a message with the
            corresponding rtype is received.
            Handlername is used for debugging purposes. """

        if self.handlers.has_key(rtype):
            die('Fetch handler for rtype %s already registered\n' %(rtype))
        self.handlers[rtype] = handler
        self.handlername[rtype] = handlername

    def handle_msg(self, user, msg):
        if len(msg['rt']) == 0:
            # Act as a master
            self.handle_reply(user, msg)
        else:
            # Act as a slave
            self.call_slave_handler(user, msg)

    def call_slave_handler(self, user, request):
        """ Fetch slave: handle incoming fetch request, call slavehandler """

        reply = None
        slavehandler = self.handlers.get(request['rt'])
        cname = request.get('c')
        if len(cname) > 0 and cname not in community.get_myself().get('communities'):
            return
        if slavehandler != None:
            reply = slavehandler(user, request)
        if request['rid'] < 0:
            return
        if reply == self.POSTPONE_REPLY:
            return
        if reply == self.SILENT_COMMUNITY_ERROR and len(cname) > 0:
            return
        if reply == None:
            warning('fetch slave returned None for %s:%s\n' % (request['rt'], request['t']))
        self.send_reply(user, request['rid'], reply)

    def handle_reply(self, user, reply):
        req = self.get_pending(user, reply['rid'])
        if req == None:
            warning('fetch master: invalid rid (%d) from %s\n' % (reply['rid'], user.tag()))
            return

        d = {'rid': reply['rid'],
             'nfields': len(reply),
             'nbytes': len(bencode(reply)),
             'rs': reply.get('rs', 'x'),
             'uid': user.get('uid'),
            }

        if reply.has_key('rs'):
            reply = None
        req.call(user, reply)

    def send_reply(self, user, rid, reply):
        """ Send reply to a fetch request. Can be a postponed reply.

            user: user to send the reply to
            rid: the request ID this reply belongs to
            reply: reply message to send to the master

            Reply value of None means an error occured.
        """

        if reply == None:
            reply = {'rs': ''}
        reply['c'] = ''
        payload = self.encode(reply, rid, '')
        if payload == None:
            return

        self.backend.send_reply(user, rid, payload)

    def get_pending(self, user, rid, pop=False):
        ureqs = pendingreqs.get(user)
        if ureqs != None:
            if pop:
                req = ureqs.pop(rid, None)
            else:
                req = ureqs.get(rid)
        else:
            req = None
        return req

    def set_pending(self, users, req):
        for user in users:
            ureqs = pendingreqs.setdefault(user, {})
            ureqs[req.rid] = req

def init(options):
    Fetcher_Plugin()
