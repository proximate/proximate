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
from gobject import timeout_add_seconds, source_remove
from random import random, randrange
from time import time

from filesharing import Share_Meta, Subscription
from plugins import Plugin, get_plugin_by_type
from support import warning
from proximateprotocol import PLUGIN_TYPE_FETCHER, PLUGIN_TYPE_FILE_SHARING, \
     PLUGIN_TYPE_MESSAGE_BOARD, PLUGIN_TYPE_NOTIFICATION, \
     PLUGIN_TYPE_COMMUNITY, valid_fs_gid, \
     PLUGIN_TYPE_STATE, PLUGIN_TYPE_SCHEDULER
from proximatestate import normal_traffic_mode
from typevalidator import validate, ANY, OPTIONAL_KEY, ZERO_OR_MORE, ONE_OR_MORE
from utils import n_lists, remove_all

SEARCH_TIMEOUT = 15             # in seconds

CACHE_UTIL = 66                 # percent of messages to spare on cleanup
MAX_MESSAGES_IN_CACHE = 256     # max number of messages in cache
CACHE_VALIDITY_PERIOD = 3600    # in seconds

SEND_VALIDITY_PERIOD = 30       # in seconds

AUTO_BROADCAST_PERIOD = 120     # in seconds

def satisfy_criteria(criteria, meta):
    if criteria != None:
        for (key, value) in criteria.items():
            if meta.get(key) != value:
                return False
    return True

def search_metas(metas, criteria, keywords):
    """ Note: storage may contain message from others """

    msgs = []
    for meta in metas:
        if not satisfy_criteria(criteria, meta):
            continue

        if keywords == None or len(keywords) == 0:
            msgs.append(meta)
            continue

        l = ['']
        for name in ('from', 'subject', 'purpose', 'msg'):
            l.append(meta[name])
        l.append('')
        s = '\n'.join(l).lower()
        for keyword in keywords:
            if s.find(keyword.lower()) >= 0:
                msgs.append(meta)
                break
    return msgs

class Search_Context:
    def __init__(self, callback, ctx=None, criteria=None, keywords=None):
        self.callback = callback
        self.ctx = ctx
        self.criteria = criteria
        self.keywords = keywords
        self.checked = {}

    def process(self, user, metas):
        filteredmetas = search_metas(metas, self.criteria, self.keywords)
        if len(filteredmetas) == 0:
            return
        newmetas = []
        for meta in filteredmetas:
            key = (user, meta['id'])
            if not self.checked.has_key(key):
                newmetas.append(meta)
                self.checked[key] = None
        if len(newmetas) > 0:
            self.callback(user, newmetas, self.ctx)

class Message_Board(Plugin):
    """ Notes on messages, see 'self.msgspec' below.

        'replyid' is used to create a message that is related to an older
        message. The 'replyid' is the old message's gid.

        If 'src' and 'dst' exist, they are guaranteed in Share_Meta
        validation to be strings.

        If 'ttl' exists, it is guaranteed to be a non-negative integer.
    """

    msgspec = {'subject': str,
               'from': str,
               'msg': str,
               OPTIONAL_KEY('replygid'): valid_fs_gid,
               OPTIONAL_KEY('url'): str,
              }

    queryspec = {'t': 'msgquery',
                 OPTIONAL_KEY('keywords'): [ONE_OR_MORE, str],
                 OPTIONAL_KEY('criteria'): {str: ANY},
                }

    queryresultspec = {'msgs': [ZERO_OR_MORE, {}]}

    def __init__(self, options):
        self.register_plugin(PLUGIN_TYPE_MESSAGE_BOARD)

        self.community = None
        self.fetcher = None
        self.fs = None
        self.state = None
        self.notification = None

        self.statusindicator = None

        self.options = options

        self.gui = None

        self.queryidx = 0

        self.keywords = []

        self.searchctxs = []

        self.notifications = {}

        self.periodidx = 0

        self.cache = {}  # maps (uid, fsid) to (timestamp, meta)

    def register_ui(self, ui):
        self.gui = ui

    def cleanup(self):
        self.state.set_plugin_variable(self.name, 'watchkeywords', self.keywords)

        savednotifications = {}
        for (key, value) in self.notifications.items():
            if value == 1:
                savednotifications[key] = 1
        self.state.set_plugin_variable(self.name, 'notifications', savednotifications)

    def cancel_search(self, sctx):
        self.searchctxs.remove(sctx)
        return False

    def msg_cache(self, user, metas):
        t = int(time())

        uid = user.get('uid')

        for meta in metas:
            self.cache[(uid, meta.get('id'))] = (t, meta)

        if len(self.cache) <= MAX_MESSAGES_IN_CACHE:
            return

        timesorted = []
        for (key, value) in self.cache.items():
            timestamp = value[0]
            timesorted.append((timestamp, key))
        timesorted.sort()
        ntodelete = len(timesorted) - (CACHE_UTIL * MAX_MESSAGES_IN_CACHE) / 100
        for i in xrange(ntodelete):
            key = timesorted[i][1]
            self.cache.pop(key)

    def process_results(self, reply):
        metas = []
        if reply == None:
            return metas
        if not validate(self.queryresultspec, reply):
            warning('msgboard: Invalid results: %s\n' % str(reply))
            return metas
        for metadict in reply['msgs']:
            meta = Share_Meta()
            if not meta.unserialize(metadict):
                warning('msgboard: Can not unserialize: %s\n' % str(metadict))
                continue
            if not self.validate_message(meta):
                warning('msgboard: Invalid meta: %s\n' % str(meta))
                continue
            metas.append(meta)
        return metas

    def got_query_results(self, user, reply, ctx):
        metas = self.process_results(reply)

        self.msg_cache(user, metas)

        for meta in metas:
            if self.is_hot(meta):
                self.notify_user(user, meta)

        for sctx in self.searchctxs:
            sctx.process(user, metas)

    def handle_message(self, user, sm):
        """ Handle messages that were found from other users' fileshares """

        if not self.validate_message(sm):
            sm['ttl'] = 0
            warning('msgboard: Invalid message: %s\n' % str(sm))
            return
        warning('New message: %s\n' % sm['subject'])

    def get_state(self):
        return self.keywords

    def is_hot(self, meta):
        if len(self.keywords) == 0 or meta.get_priv('mine'):
            return False
        return len(search_metas([meta], None, self.keywords)) > 0

    def modify_state(self, add, keyword):
        if add:
            if keyword in self.keywords:
                return
            self.keywords.append(keyword)
        else:
            remove_all(self.keywords, keyword)
        self.cleanup()

    def notify_user(self, user, meta):
        uid = user.get('uid')
        key = (uid, meta['id'])
        if key in self.notifications:
            return
        self.notifications[key] = 0
        msg = 'User %s has a message titled: %s. View it?' % (user.tag(), meta['subject'])
        self.notification.notify_with_response(msg, self.view_message, (key, meta))

    def view_message(self, response, msg, ctx):
        (key, meta) = ctx
        self.notifications[key] = 1
        if response == self.notification.RESPONSE_DELETED:
            return True
        self.gui.view_message(meta)
        return True

    def all_metas(self):
        metas = []
        for share in self.fs.get_shares(purpose=self.name):
            if share.meta.get_priv('mine'):
                metas.append(share.meta)
        return metas

    def read_state(self):
        l = self.state.get_plugin_variable(self.name, 'watchkeywords')
        if l != None:
            self.keywords = l

        notifications = self.state.get_plugin_variable(self.name, 'notifications')
        if notifications != None:
            self.notifications = notifications

    def handle_msgpush(self, user, request):
        self.got_query_results(user, request, None)
        return None

    def handle_request(self, user, request):
        """ Handle incoming queries. Search through Share_Metas. """

        if request.get('t') == 'msgpush':
            return self.handle_msgpush(user, request)

        if not validate(self.queryspec, request):
            warning('Invalid msgboard query: %s\n' % str(request))
            return None
        keywords = request.get('keywords')

        criteria = request.get('criteria')
        if criteria == None:
            criteria = {}
        criteria.setdefault('src', self.community.myuid)

        metas = search_metas(self.all_metas(), criteria, keywords)
        if not normal_traffic_mode():
            t = int(time())
            metas = filter(lambda meta: self.test_send_time(meta, t), metas)
            for meta in metas:
                self.set_send_time(meta, t)

        serializedmetas = []
        for meta in metas:
            serializedmetas.append(meta.serialize())

        if len(serializedmetas) == 0:
            if normal_traffic_mode():
                return {'msgs': []}
            else:
                return self.fetcher.POSTPONE_REPLY

        if self.fetcher.is_fetch_community_efficient():
            com = self.community.get_default_community()

            # Broadcast messages in bundles of three messages
            push = {'t': 'msgpush'}
            for metabundle in n_lists(serializedmetas, 3):
                push['msgs'] = metabundle
                self.fetcher.fetch_community(com, self.name, push, None, ack=False)
            return self.fetcher.POSTPONE_REPLY

        return {'msgs': serializedmetas}

    def publish(self, d, path=None, save=True):
        sm = Share_Meta(d)
        sm.replicate(withidentity=True)
        if not self.validate_message(sm):
            warning('Not creating an invalid msgboard message: %s\n' % str(sm))
            return None
        share = self.fs.add_share(purpose=self.name, sharemeta=sm, save=save)
        if share == None:
            return None
        return share.meta

    def delete(self, meta):
        shareid = meta.get('id')
        self.fs.remove_share(self.fs.get_share(shareid))
        self.gui.message_deleted_cb(meta)

    def search(self, callback, ctx=None, criteria=None, keywords=None, replicated=False, fetch=True):
        """ The caller gets an indetermistic number of result callbacks.
            Empty keywords, or keywords == None, means get all messages. """

        if criteria == None:
            criteria = {}

        sctx = Search_Context(callback, ctx=ctx, criteria=criteria, keywords=keywords)

        if fetch:
            self.searchctxs.append(sctx)
            timeout_add_seconds(SEARCH_TIMEOUT, self.cancel_search, sctx)

            self.statusindicator.set_status('Searching messages', timeout=SEARCH_TIMEOUT)

            # Query others
            req = {'t': 'msgquery'}
            if keywords != None:
                req['keywords'] = keywords
            req['criteria'] = criteria

            com = self.community.get_default_community()
            self.fetcher.fetch_community(com, self.name, req, self.got_query_results)

            self.query_cache(sctx)

        # Then query myself
        sctx.process(self.community.get_myself(), self.all_metas())

    def set_send_time(self, meta, t):
        meta.set_priv('sendtime', t)

    def test_send_time(self, meta, t):
        """ Returns True iff message should be sent """
        sendtime = meta.get_priv('sendtime')
        tlimit = t - SEND_VALIDITY_PERIOD
        if sendtime == None or sendtime < tlimit or t < sendtime:
            return True
        else:
            return False

    def query_cache(self, sctx):
        timelimit = int(time()) - CACHE_VALIDITY_PERIOD
        d = {}
        todelete = []
        for (key, value) in self.cache.items():
            (uid, id) = key
            (mtime, meta) = value
            user = self.community.get_user(uid)
            if user == None or mtime < timelimit:
                todelete.append(key)
                continue
            d.setdefault(user, []).append(meta)
        for key in todelete:
            self.cache.pop(key)
        for (user, metas) in d.items():
            sctx.process(user, metas)

    def query_messages(self, showmine=False, target=None):
        """ Start an asynchronous query process. Results are displayed in the
            GUI as they come in from peers. """

        criteria = None
        if target != None:
            criteria = {'community': target.get('name')}

        # Generate a new query context that is passed along with the query.
        # This structure is used to process incoming results, and to
        # reject results from older queries.
        self.queryidx += 1
        queryctx = (self.queryidx, [], criteria)

        fetch = not showmine
        self.search(self.collect_messages, ctx=queryctx, criteria=criteria, fetch=fetch)

        if showmine:
            self.statusindicator.set_status(None)

    def collect_messages(self, user, metas, queryctx):
        (queryidx, queryresults, criteria) = queryctx
        if queryidx != self.queryidx:
            return

        queryresults += metas

        # First, take messages published by myself so that others may not inject
        # gids my messages into my view.
        gids = {}
        mymetas = []
        for meta in queryresults:
            if not meta.get_priv('mine'):
                continue
            gid = meta.get('gid')
            if gid != None:
                gids[gid] = None
            mymetas.append(meta)

        # Second, take results from others
        metas = []
        for meta in queryresults:
            if meta.get_priv('mine'):
                continue
            gid = meta.get('gid')
            if gid != None and gid in gids:
                continue
            gids[gid] = None
            metas.append(meta)

        # Put my metas last
        metas += mymetas

        self.gui.update_message_list(metas)

    def periodic(self, t, ctx):
        if not self.fetcher.is_fetch_community_efficient():
            return False
        if random() >= (5.0 / AUTO_BROADCAST_PERIOD):
            return True
        l = []
        t = int(time())
        for meta in self.all_metas():
            if self.test_send_time(meta, t):
                l.append((meta['id'], meta))
        l.sort()
        if len(l) == 0:
            return True
        meta = l[self.periodidx % len(l)][1]
        self.periodidx = (self.periodidx + 1) % len(l)
        self.set_send_time(meta, t)
        push = {'t': 'msgpush',
                'msgs': [meta.serialize()]}
        com = self.community.get_default_community()
        self.fetcher.fetch_community(com, self.name, push, None, ack=False)
        return True

    def ready(self):
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        self.fetcher = get_plugin_by_type(PLUGIN_TYPE_FETCHER)
        self.fs = get_plugin_by_type(PLUGIN_TYPE_FILE_SHARING)
        self.state = get_plugin_by_type(PLUGIN_TYPE_STATE)
        self.notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)
        self.sch = get_plugin_by_type(PLUGIN_TYPE_SCHEDULER)

        self.sch.call_periodic(5 * self.sch.SECOND, self.periodic)

        self.statusindicator = self.notification.get_progress_indicator('Msg board')

        # Subscribe to fileshares that are msgboard messages
        self.fs.subscribe(Subscription(purpose=self.name, callback=self.handle_message))

        self.fetcher.register_handler(self.name, self.handle_request, self.name)

        self.read_state()

    def validate_message(self, sm):
        return validate(self.msgspec, sm.d)

def init(options):
    Message_Board(options)
