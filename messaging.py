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
import time
import hashlib
from binascii import hexlify
from random import random

from typevalidator import ZERO_OR_MORE, ONE_OR_MORE, validate, OPTIONAL_KEY
from plugins import Plugin, get_plugin_by_type
from support import warning, debug
from proximateprotocol import PLUGIN_TYPE_COMMUNITY, PLUGIN_TYPE_FETCHER, \
     PLUGIN_TYPE_MESSAGING, valid_uid, valid_community, \
     PLUGIN_TYPE_NOTIFICATION, PLUGIN_TYPE_SETTINGS, PLUGIN_TYPE_VIBRA
from proximatestate import normal_traffic_mode
from utils import str_to_int

MAX_CTIME_STR_LENGTH = 30
MAX_MSG_STR_LENGTH = 1024
CONVERSATION_MAX_LENGTH = 500
MESSAGE_CONTEXT_LEN = 2
MESSAGE_EXPIRATION = 4 * 3600 # 4 hours

def addr_from_user(user):
    """ This function creates 'u:uid' address from User object. """
    return 'u:%s' % (user.get('uid'))

def addr_from_community(community, key=''):
    """ This function creates 'c:key:name' address from Community object. """
    return 'c:%s:%s' % (key, community.get('name'))

def user_from_addr(community, addr, safe=True):
    uid = addr.split(':')[1]
    user = community.get_user(uid)
    if safe and user == community.get_myself():
        return None
    return user

def community_from_addr(community, addr):
    cname = addr.split(':')[2]
    l = community.find_communities(cname, peer=True)
    if len(l) == 0:
        return None
    return l[0]

def decode_addr(addr):
    is_community = (addr[0] == 'c')
    l = addr.split(':')
    if is_community:
        return (True, l[1], l[2])
    else:
        return (False, None, l[1])

def valid_addr(addr):
    l = addr.split(':')
    if not ((len(l) == 2 and l[0] == 'u') or (len(l) == 3 and l[0] == 'c')):
        return False
    if l[0] == 'u' and not valid_uid(l[1]):
        return False
    if l[0] == 'c' and not valid_community(l[2]):
        return False
    return True

def is_addr_community(addr):
    return addr[0] == 'c'

# global monotonically increasing message sequence number
msg_seq = 0

class Message:
    """ Class for chat message from 'sender' to 'target' """
    def __init__(self, msg=None, sender_addr=None, target_addr=None, parent_sha1=''):
        global msg_seq

        self.fields = None

        self.error = False

        self.rtime = int(time.time())

        if msg == None:
            return

        self.fields = [None,
                       parent_sha1,
                       str(self.rtime) + ':' + str(msg_seq),
                       sender_addr,
                       target_addr,
                       msg]

        msg_seq = msg_seq + 1

        # compute MESSAGEID
        m = hashlib.sha1()
        for f in self.fields[1:]:
            m.update(f)
        self.fields[0] = m.digest()

    def from_list(self, fields):
        self.fields = fields

    def to_list(self):
        return self.fields

    def validate(self):
        if not self.fields or len(self.fields) < 6:
            return False

        # 0. Check field lengths
        if len(self.fields[0]) != 20:
            return False

        if not (len(self.fields[1]) == 0 or len(self.fields[1]) == 20):
            return False

        if len(self.fields[2]) > MAX_CTIME_STR_LENGTH:
            return False

        if len(self.fields[5]) > MAX_MSG_STR_LENGTH:
            return False

        # 1. Check SHA1 sum
        m = hashlib.sha1()
        for f in self.fields[1:]:
            m.update(f)

        if m.digest() != self.fields[0]:
            return False

        # 2. Check addresses
        l = self.get_sender_addr().split(':')
        if len(l) != 2 or l[0] != 'u' or not valid_uid(l[1]):
            return False

        if not valid_addr(self.get_target_addr()):
            return False

        # 3. Check ctime
        l = self.get_ctime()
        if len(l) < 2:
            return False
        timet = str_to_int(l[0], -1)
        seqnumber = str_to_int(l[1], -1)
        return timet >= 0 and seqnumber >= 0

    def get_msg(self):
        return self.fields[5]

    def get_msgid(self):
        return self.fields[0]

    def get_parentid(self):
        return self.fields[1]

    def get_ctime(self):
        return self.fields[2].split(':')

    def get_rtime(self):
        return self.rtime

    def set_rtime(self, rtime):
        self.rtime = rtime

    def get_sender_addr(self):
        return self.fields[3]

    def get_target_addr(self):
        return self.fields[4]

    def __str__(self):
        return str(self.fields)


class Conversation:
    """
    This class holds information about a single conversation.
    Works only as a data storage of the conversation graph formed
    by msgids and parentids.
    """

    def __init__(self, target_addr):
        self.target_addr = target_addr

        # dictionary of messages using msgid as key
        self.msgdict = {}

        # msgid mapped to list of msgid's of children
        self.childdict = {}

        # root nodes of trees in msgdict and childdict
        self.roots = []

        # msgid of head node in the forest
        self.headid = None

    def length(self):
        return len(self.msgdict)

    def get_roots(self):
        return self.roots

    def clear(self):
        self.msgdict = {}
        self.childdict = {}
        self.roots = []
        self.headid = None

    def has_msgid(self, msgid):
        return msgid in self.msgdict

    def get_msg(self, msgid, default=None):
        return self.msgdict.get(msgid, default)

    def get_children(self, msgid, default=[]):
        return self.childdict.get(msgid, default)

    def is_community(self):
        return is_addr_community(self.target_addr)

    def add_msg(self, msg, set_head=False):
        parentid = msg.get_parentid()
        msgid = msg.get_msgid()

        if msgid in self.msgdict:
            warning('add_msg(): Attempted to add same message twice\n')
            return

        # add to msgdict
        self.msgdict[msgid] = msg

        # update children-list of parent
        if parentid != '':
            # Create a new list of children if it does not exist
            parent_children = self.childdict.setdefault(parentid, [])
            parent_children.append(msgid)

        has_parent = self.msgdict.has_key(parentid)
        children = self.childdict.get(msgid, [])

        # if parent of this node is not in msgdict, this is new root node
        if not has_parent:
            self.roots.append(msgid)

        # join trees by removing roots of child trees
        for childid in children:
            self.roots.remove(childid)

        if set_head:
            self.headid = msgid


    def remove_msg(self, msg):
        parentid = msg.get_parentid()
        msgid = msg.get_msgid()

        self.msgdict.pop(msgid)

        if parentid != '':
            parent_children = self.childdict.get(parentid)
            parent_children.remove(msgid)

        has_parent = self.msgdict.has_key(parentid)
        children = self.childdict.get(msgid, [])

        # if parent of this node is not in msgdict, this was root node
        if not has_parent:
            self.roots.remove(msgid)

        # split trees by adding children as new trees
        for childid in children:
            self.roots.append(childid)

    def tag(self):
        (iscom, key, name) = decode_addr(self.target_addr)
        return name

    def get_head(self):
        if not self.headid:
            return None
        return self.msgdict[self.headid]

    def get_headid(self):
        return self.headid

    def get_subconversations(self):
        return [Tree_Iter(self, root) for root in self.roots]

class Tree_Iter:
    """ Tree_Iter class is used to iterate through a
        continuous subtree of conversation graph. """
    def __init__(self, conversation, root):
        self.c = conversation
        self.root = root

    def __iter__(self):
        self.queue = [self.root]
        return self

    def peek(self):
        if not self.queue:
            return None

        nodeid = self.queue[0]
        return self.c.msgdict[nodeid]

    def next(self):
        if not self.queue:
            raise StopIteration

        nodeid = self.queue.pop(0)
        children = self.c.childdict.get(nodeid, [])
        for childid in children:
            self.queue.append(childid)

        return self.c.msgdict[nodeid]

class Messaging_Plugin(Plugin):
    msgreplyspec = {'parentid' : str,
                    'children': [ZERO_OR_MORE, str],
                   }

    requestreplyspec = {'msg': [ONE_OR_MORE, str],
                        'children': [ZERO_OR_MORE, str],
                       }

    requestheadsreplyspec = {'heads': [ZERO_OR_MORE, [ONE_OR_MORE, str]]}

    # command messages
    MESSAGING_ACK = 'messaging ack'
    MESSAGING_END = 'messaging end'
    COMMUNITY_CHAT_ACTIVE = 'community chat active'
    COMMUNITY_CHAT_UPDATE = 'community chat update'
    COMMUNITY_HISTORY_REQUEST = 'community history request'
    U2U_MESSAGE = 'u2u message'
    COMMUNITY_MESSAGE = 'community message'
    MESSAGING_ERROR = 'messaging error'
    PROXIMATE_MAIL = 'proximate mail'
    MAILING_HEADERS = 'mailing headers'
    MAILING_GET = 'mailing get'
    MAILING_DELETE = 'mailing delete'

    COMMUNITY_CHAT_NOTIFY = 'community chat notify'

    def __init__(self, options):
        self.register_plugin(PLUGIN_TYPE_MESSAGING)

        self.chatcontext = options.chatcontext

    def ready(self):
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        self.fetcher = get_plugin_by_type(PLUGIN_TYPE_FETCHER)
        self.notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)
        self.vibra = get_plugin_by_type(PLUGIN_TYPE_VIBRA)
        self.myself = self.community.get_myself()
        self.my_addr = addr_from_user(self.myself)

        self.fetcher.register_handler(PLUGIN_TYPE_MESSAGING, self.handle_messaging_command, 'messaging')

        self.conversations = {}

        self.new_message_cb = []
        self.delete_message_cb = []
        self.change_message_cb = []

        settings = get_plugin_by_type(PLUGIN_TYPE_SETTINGS)
        self.vibra_chat_setting = settings.register('vibra.chat', bool, 'Vibrate on community chat messages', default=False)
        self.vibra_private_setting = settings.register('vibra.private', bool, 'Vibrate on private chat messages', default=False)

    def register_ui(self, ui):
        self.messaging_gui = ui
        self.new_message_cb.append(self.messaging_gui.new_message_cb)
        self.delete_message_cb.append(self.messaging_gui.delete_message_cb)
        self.change_message_cb.append(self.messaging_gui.change_message_cb)

    def handle_messaging_command(self, user, request):
        """
        Handles requests from fetcher. Really just a multiplexer function,
        real handling is done in separate classes.
        """

        t = request.get('t')
        if t == 'msg':
            validator = {'msg': [ONE_OR_MORE, str],
                         OPTIONAL_KEY('context'): [ZERO_OR_MORE, {}]
                        }
            if not validate(validator, request):
                warning('Invalid messaging request: %s\n' %(str(request)))
                return None

            l = request['msg']
            if len(l) < 6:
                warning('Invalid messaging request: %s\n' % str(request))
                return None

            msg = Message()
            msg.from_list(l)

            # check internal validity
            if not msg.validate():
                return None

            if self.chatcontext:
                context = request.get('context')
            else:
                context = None

            return self.handle_message(user, msg, context)

        elif t == 'request':
            if not validate({'msgid': str}, request):
                warning('Invalid messaging request: %s\n' % str(request))
                return None

            return self.handle_request(user, request['msgid'])

        elif t == 'request_heads':
            if not validate({'addrs' : [ZERO_OR_MORE, str]}, request):
                warning('Invalid heads request: %s\n' % str(request))
                return None

            return self.handle_request_heads(user, request['addrs'])

        return {}

    def announce_new_message(self, c, msg):
        visible = False
        for callback in self.new_message_cb:
            if callback(c, msg):
                visible = True

        if not visible and self.vibra != None and msg.get_sender_addr() != self.my_addr:
            if c.is_community():
                if self.vibra_chat_setting.value == True:
                    self.vibra.vibrate()
            else:
                if self.vibra_private_setting.value == True:
                    self.vibra.vibrate()

    def get_conversation(self, addr):
        conversation = self.conversations.get(addr)
        if conversation == None:
            conversation = Conversation(addr)
            self.conversations[addr] = conversation
        return conversation

    def join_conversation(self, community):
        target_addr = addr_from_community(community)
        return self.get_conversation(target_addr)

    def close_conversation(self, c):
        self.conversations.pop(c.target_addr)

    def close_all_conversations(self):
        self.conversations = {}

    def open_user_conversation(self, user):
        target_addr = addr_from_user(user)
        return self.get_conversation(target_addr)

    def open_community_conversation(self, community):
        if not self.community.is_member(self.myself, community):
            self.community.join_community(community, temporary=True)
        target_addr = addr_from_community(community)
        return self.get_conversation(target_addr)

    def cleanup_conversation(self, c):
        while c.length() > CONVERSATION_MAX_LENGTH:
            roots = c.get_roots()

            if len(roots) == 0:
                return

            oldest = c.get_msg(roots[0])
            for rid in roots[1:]:
                r = c.get_msg(rid)
                if r.get_rtime() < oldest.get_rtime():
                    oldest = r

            for cb in self.delete_message_cb:
                cb(c, oldest)

            c.remove_msg(oldest)


    def say(self, c, msg):
        parentid = ''

        # It is impossible to know which tree the user is
        # really continuing. Best guess: the one which has
        # head message, and hoping that others will also
        # start using the same tree.
        head = c.get_head()
        if head:
            parentid = head.get_msgid()

        m = Message(msg, self.my_addr, c.target_addr, parentid)

        c.add_msg(m, set_head=True)

        self.cleanup_conversation(c)

        request = {'t': 'msg', 'msg' : m.to_list()}

        ctxmsgs = []
        if self.chatcontext:
            context = []
            for i in range(MESSAGE_CONTEXT_LEN):
                if head == None:
                    break
                ctxmsgs.append(head)
                context.append({'msg': head.to_list(), 'children': []})
                head = c.get_msg(head.get_parentid())
            request['context'] = context

        ctx = (c, m, ctxmsgs)
        if c.is_community():
            community = community_from_addr(self.community, c.target_addr)
            if community != None:
                ack = normal_traffic_mode()
                if not self.fetcher.fetch_community(community, PLUGIN_TYPE_MESSAGING, request, self.got_message_reply, ctx, ack=ack):
                    m.error = True
        else:
            user = user_from_addr(self.community, c.target_addr)
            if not self.fetcher.fetch(user, PLUGIN_TYPE_MESSAGING, request, self.got_user_message_reply, ctx):
                self.notification.notify('Unable to a send message to %s' % user.tag(), True)
                m.error = True

        self.announce_new_message(c, m)

    def handle_message(self, user, msg, context):
        #if random() > 0.3:
        #    debug('Dropping message %s\n' % msg.get_msg())
        #    return

        debug('Received message %s\n' % msg.get_msg())

        if context != None:
            for item in context:
                self.got_request_reply(user, item, max_depth=0)

        msgid = msg.get_msgid()
        sender_addr = msg.get_sender_addr()
        target_addr = msg.get_target_addr()

        # validate message source and target:
        #   1. sending user uid must match with sender address
        #   2. if target is community, user and myself
        #      must be member of the community
        #   3. if target is user, it must be myself
        is_community, key, uid = decode_addr(sender_addr)
        if user.get('uid') != uid:
            warning('User \'%s\' is spoofing\n' % user.get('uid'))
            return None

        is_community, key, targetid = decode_addr(target_addr)
        if is_community:
            if not (targetid in user.get('communities') and
                    targetid in self.myself.get('communities')):
                warning('User \'%s\' is not a member of the target community\n' % user.get('uid'))
                return None
        else:
            if targetid != self.myself.get('uid'):
                return None

        # when we receive a message, the corresponding conversation
        # is identified from message as:
        #    user-to-user : from sender_addr
        #    community    : from target_addr
        if is_community:
            ckey = target_addr
        else:
            ckey = sender_addr

        # if message has no parent -> new conversation
        # if message has parent -> continue earlier conversation
        parentid = msg.get_parentid()
        c = self.get_conversation(ckey)

        # discard duplicates
        if c.has_msgid(msgid):
            return {}

        if not c.is_community():
            if user_from_addr(self.community, sender_addr) == None:
                warning('Invalid message sender (yourself or unknown user)\n')
                return None

        # get other children of parent for reply
        if parentid != '':
            other_children = c.get_children(parentid)[:]
        else:
            other_children = []

        c.add_msg(msg, set_head=True)

        self.cleanup_conversation(c)

        self.announce_new_message(c, msg)

        # if message has parent:
        #    if we don't have it -> request it and return {}
        #    if we have it -> return msg_reply with parent's other children
        # if message does not have parent -> return empty dictionary
        if self.chatcontext and parentid != '' and (not is_community or normal_traffic_mode()):
            if not c.has_msgid(parentid):
                self.request_message(user, parentid, max_depth=10)
            else:
                # XXX: Remove: 't' field after some time
                return {'t': 'msg_reply', 'parentid': parentid, 'children': other_children}

        return {}

    def got_message_reply(self, user, result, ctx):
        (c, m, ctxmsgs) = ctx
        if result == None:
            return
        if not validate(self.msgreplyspec, result):
            return

        for m in ctxmsgs:
            if m.error:
                m.error = False
                for cb in self.change_message_cb:
                    cb(c, m)

        parentid = result['parentid']
        children = result['children']

        # find conversation with parentid
        c = None
        for ci in self.conversations.values():
            if ci.has_msgid(parentid):
                c = ci
                break

        if c == None:
            return

        # request children if we don't have them already
        for childid in children:
            if not c.has_msgid(childid):
                self.request_message(user, childid, max_depth=10)

    def got_user_message_reply(self, user, result, ctx):
        (c, m, ctxmsgs) = ctx
        if result == None:
            self.notification.notify('Unable to a send message to %s' % user.tag(), True)
            m.error = True
            for cb in self.change_message_cb:
                cb(c, m)
        else:
            self.got_message_reply(user, result, ctx)

    def request_message(self, user, msgid, max_depth=0):
        """ Request message from user using msgid. Parameter
            'max_depth' defines the maximum amount of ancestors
            that are requested after this message. """

        if not self.chatcontext:
            return

        debug('Requesting message %s\n' % hexlify(msgid))
        request = {'t': 'request', 'msgid': msgid}
        self.fetcher.fetch(user, PLUGIN_TYPE_MESSAGING, request, self.got_request_reply, ctx=max_depth)

    def got_request_reply(self, user, result, max_depth):
        if not validate(self.requestreplyspec, result):
            return

        msg_list = result['msg']
        children = result['children']

        m = Message()
        m.from_list(msg_list)
        if not m.validate():
            warning('Invalid message received from request\n')
            return

        debug('Received requested message %s (%i)\n' % (m.get_msg(), max_depth))

        ctime = int(m.get_ctime()[0])
        if time.time() - ctime >= MESSAGE_EXPIRATION:
            debug('Rejecting expired message: %s\n' % m.get_msg())
            return

        # when we receive a message, the corresponding conversation
        # is identified:
        #    user-to-user : from sender_addr or target_addr (!= my_addr)
        #    community    : from target_addr
        target_addr = m.get_target_addr()
        sender_addr = m.get_sender_addr()
        if is_addr_community(target_addr):
            ckey = target_addr
        else:
            if sender_addr == self.my_addr:
                ckey = target_addr
            else:
                ckey = sender_addr

        c = self.get_conversation(ckey)

        # discard duplicates
        msgid = m.get_msgid()
        if c.has_msgid(msgid):
            return

        # add message and set it as new head if it doesn't have children
        if len(c.get_children(msgid)) > 0:
            c.add_msg(m)
        else:
            c.add_msg(m, set_head=True)

        self.cleanup_conversation(c)

        self.announce_new_message(c, m)

        # if maximum depth is reached, do not continue to request
        # parent and children
        if max_depth <= 0:
            return

        # request parent if we don't have it already
        parentid = m.get_parentid()
        if parentid != '':
            if not c.has_msgid(parentid):
                self.request_message(user, parentid, max_depth=max_depth-1)

        # request children if we don't have them already
        for childid in children:
            if not c.has_msgid(childid):
                self.request_message(user, childid, max_depth=max_depth-1)

    def handle_request(self, user, msgid):

        # find conversation with msgid
        c = None
        for ci in self.conversations.values():
            if ci.has_msgid(msgid):
                c = ci
                break

        # if we don't have a stored conversation with requesting user
        if not c:
            debug('Unknown user\n')
            return None

        target_addr = c.target_addr

        msg = c.get_msg(msgid)

        # if we don't have the requested message
        if not msg:
            return None

        # if we get a request for a message of community conversation, we
        # require the community membership of the requesting user
        if c.is_community():
            if not (c.tag() in user.get('communities')):
                warning('User \'%s\' is not a member of the target community\n' % user.get('uid'))
                return None

        # check if UID fails
        if not ((msg.get_target_addr() == target_addr) or
                (msg.get_sender_addr() == target_addr)):
            debug('UID fail\n')
            return None

        if msg.error:
            msg.error = False
            for cb in self.change_message_cb:
                cb(c, msg)

        children = c.get_children(msgid, [])

        # XXX: Remove 't' field after some months
        return {'t': 'request_reply', 'msg': msg.to_list(), 'children': children}

    def user_appears(self, user):
        if not self.chatcontext:
            return

        # find shared community conversations
        my_communities = self.myself.get('communities')
        if my_communities == None:
            my_communities = []

        user_communities = user.get('communities')
        if user_communities == None:
            user_communities = []

        addrs = []
        for c in my_communities:
            if c in user_communities and normal_traffic_mode():
                addr = 'c::%s' % c
                addrs.append(addr)

        # append private conversation address to get private conversation head
        # if it exists
        addrs.append(self.my_addr)

        request = {'t': 'request_heads', 'addrs': addrs}
        self.fetcher.fetch(user, PLUGIN_TYPE_MESSAGING, request, self.got_request_heads_reply, ctx=addrs)

    def handle_request_heads(self, user, addrs):
        heads = []
        for addr in addrs:
            if not valid_addr(addr):
                return None
            (is_community, key, tag) = decode_addr(addr)

            # skip address if user is not a member of the community, or
            # address doesn't match private conversation with the user
            if is_community:
                if tag not in user.get('communities'):
                    continue
            else:
                if tag != user.get('uid'):
                    continue

            c = self.conversations.get(addr)
            if c:
                headid = c.get_headid()
                if headid:
                    heads.append([addr, headid])

        # XXX: Remove 't' field after some time
        return {'t': 'request_heads_reply', 'heads': heads}

    def got_request_heads_reply(self, user, result, addrs):
        if not validate(self.requestheadsreplyspec, result):
            return

        heads = result['heads']

        for head in heads:
            addr = head[0]

            # check that we requested a head for this address, if not
            # then skip this addr
            if addr not in addrs:
                continue

            # request all heads received for this address
            for msgid in head[1:]:
                c = self.get_conversation(addr)
                if not c.has_msgid(msgid):
                    self.request_message(user, msgid, max_depth=10)

def init(options):
    Messaging_Plugin(options)
