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
from gobject import io_add_watch, IO_IN
import socket
from random import randint

from bencode import fmt_bdecode, bencode
from ioutils import create_udp_socket, send_broadcast, TCP_Queue
from plugins import Plugin, get_plugins, get_plugin_by_type
from support import warning, info, debug, get_debug_mode
from proximateprotocol import DEFAULT_COMMUNITY_NAME, FRIENDS_COMMUNITY_NAME, \
     BLACKLIST_COMMUNITY_NAME, USER_STATUS_LIST, \
     TP_HELLO, TP_QUIT, TP_SCAN_INTERVAL, TP_CONNECT_TIMEOUT, \
     PROXIMATE_PROTOCOL_VERSION, valid_community, \
     valid_nick, valid_port, valid_uid, valid_protocol_version, \
     PLUGIN_TYPE_COMMUNITY, PLUGIN_TYPE_FETCHER, \
     PLUGIN_TYPE_NOTIFICATION, PLUGIN_TYPE_SCHEDULER, PROFILE_ICON_CHANGED, \
     PLUGIN_TYPE_NETWORK_CONTROL, \
     PLUGIN_TYPE_SETTINGS, DEFAULT_PROXIMATE_PORT, TP_MIN_PORT, TP_MAX_PORT
from proximatestate import create_community, find_communities, get_community_dir, \
     get_broadcast_ports, delete_community, \
     seek_community_icon_name, get_myself, get_ordinary_community, get_user, \
     get_users,  get_user_dir, save_user, \
     save_community_icon, save_communities, save_face, seek_face_name, \
     create_user, delete_face, create_user_communities, delete_community_icon, \
     normal_traffic_mode
from typevalidator import validate, ZERO_OR_MORE
from utils import read_file_contents, Rate_Limiter
from pathname import get_path, FRIEND_COMMUNITY_ICON
from meta import is_unsigned_int

from user import User
from communitymeta import Community

community = None

REQUEST_INTERVAL = 300 // TP_SCAN_INTERVAL
ICON_PUSH_INTERVAL = 60

# Avoid icon transfers with huge number of online users
MAX_ICON_ACTIVE = 30

class Community_Plugin(Plugin):
    IP_NETWORK = 0

    def __init__(self, options):
        self.register_plugin(PLUGIN_TYPE_COMMUNITY)
        self.register_server(TP_HELLO, Hello_Server)

        self.fetcher = None
        self.fetchhandlers = {
            TP_HELLO: self.handle_hello,
            'uprofile': self.handle_user_profile_fetch,
            'iconrequest': self.handle_icon_request,
            'iconpush': self.handle_icon_push,
            'cprofile': self.handle_community_profile_fetch,
            'cprofiles': self.handle_community_profiles_fetch,
            'cinvite': self.handle_invite_community,
            }

        self.notify = None
        self.net = None
        self.community_gui = None
        self.req_counter = 0
        self.activeport = options.activeport

        # Note ipactive is not dependent on udp_listen and udp_send variables
        self.ipactive = True

        self.activeusers = {}

        self.remoteusers = {}
        for user in self.get_users(False):
            remotes = user.get('remotes')
            if remotes != None and len(remotes) > 0:
                self.remoteusers[user] = 0

        self.myself = get_myself()
        self.myuid = self.myself.get('uid')

        self.udp_listen = (options.udpmode & 1) != 0
        self.udp_send = (options.udpmode & 2) != 0
        if not self.udp_listen or not self.udp_send:
            info('UDP broadcast listen: %s send: %s\n' % (self.udp_listen, self.udp_send))

        self.blacklist = {}
        self.blistcom = self.create_community(BLACKLIST_COMMUNITY_NAME, peer=False, public=False)
        self.blistcom.set('invisible', True)

        self.iconfetchlimiters = {'user': Rate_Limiter(ICON_PUSH_INTERVAL)}

        self.personal_communities = options.personal_communities

        # Create a community of friends, if it doesn't already exist
        friends = self.get_friend_community()
        if friends == None:
            friends = self.create_community(FRIENDS_COMMUNITY_NAME, peer=False, public=False, desc='My friends')
            self.set_community_icon(friends, get_path(FRIEND_COMMUNITY_ICON))

    def register_ui(self, ui):
        self.community_gui = ui

    def add_friend(self, user):
        assert(isinstance(user, User))
        self.get_friend_community().add_member(user)
        self.announce_user_change(user)

    def add_member(self, com, user):
        """ Add member to a personal community. """

        assert(isinstance(com, Community))
        assert(isinstance(user, User))

        if com.get('peer'):
            warning('Can not add member to peer community\n')
            return False

        if com == self.blistcom:
            self.blacklist[user] = None

        com.add_member(user)
        self.save_communities([com])
        self.announce_user_change(user, allowme=True)
        self.notify.notify('%s added to community %s' % (user.tag(), com.get('name')))
        return True

    def add_or_update_user(self, uid, updatelist, profileversion, ip, port, profile=None):
        user = get_user(uid)
        newuser = (user == None)
        if newuser:
            user = create_user(uid)
            if not user:
                warning('community: Unable to create a new user %s\n' % uid)
                return

        if ip != None:
            user.set('ip', ip)
            user.set('port', port)

        if newuser or user.get('v') != profileversion:
            user.update_attributes(updatelist, user.get('v'))

            if profile != None:
                self.got_user_profile(user, profile, None)
            elif not user.inprogress:
                debug('Fetching new profile from user %s\n' % user.tag())
                request = {'t': 'uprofile'}
                if self.fetcher.fetch(user, PLUGIN_TYPE_COMMUNITY, request, self.got_user_profile):
                    user.inprogress = True

        elif not user.present and not user.inprogress:
            # User appears and user profile is already up-to-date
            self.request_user_icon(user)
            self.fetch_community_profiles(user)

        if user.update_presence(True):
            self.announce_user(user)

    def broadcast(self, msg):
        if not self.get_network_state(self.IP_NETWORK):
            # Act like there is no IP network
            return

        for (dev, state) in self.net.get_interfaces().items():
            (ip, bcast) = state
            if ip == None:
                continue
            for port in get_broadcast_ports():
                send_broadcast(bcast, port, msg)

    def cleanup(self):
        self.log_users(0, None)

        if self.udp_send:
            self.broadcast(self.gen_rpc_bye())

        for user in self.activeusers.keys():
            self.depart_user(user)

    def create_community(self, name, peer=True, public=True, desc=None):
        existing = self.find_communities(name, peer=peer, public=public)
        if len(existing) > 0:
            assert(len(existing) == 1)
            community = existing[0]
        else:
            community = create_community(name)
            community.set('peer', peer)
            community.set('public', public)
        community.set('creator', self.myself.get('nick'))
        community.set('creatoruid', self.myself.get('uid'))
        community.set('description', desc)
        self.save_communities([community])

        if peer == False:
            self.announce_user_change(self.myself, allowme=True)
        return community

    def create_udp_listener(self):
        if self.activeport != None:
            # Port specified in the command line
            port = self.activeport
        else:
            port = self.listener_port_setting.value
        rfd = create_udp_socket('', port, False, reuse = True)
        if rfd == None:
            warning('Can not listen to UDP broadcasts on port %d\n' % port)
            return

        info('Listening to UDP broadcasts on port %d\n' % port)
        rfd.setblocking(False)
        io_add_watch(rfd, IO_IN, self.udp_listener_read)

    def depart_user(self, user):
        """ This is called when user is denounced or the program quits.
            In the latter case this method is called for all active users. """
        user.update_presence(False)

    def denounce_user(self, user):
        try:
            self.activeusers.pop(user)
        except KeyError:
            # we got a false bye-bye message
            return
        if not user.is_present():
            return
        if get_debug_mode():
            self.notify.user_notify(user, 'disappears')

        user.set('ip', None)
        user.set('port', None)

        self.depart_user(user)

        if self.community_gui != None:
            self.community_gui.user_disappears(user)

        for plugin in get_plugins():
            plugin.user_disappears(user)

        if user.dirty:
            self.save_user(user)

    def announce_community_change(self, com):
        if self.community_gui != None:
            self.community_gui.community_changes(com)

        for plugin in get_plugins():
            plugin.community_changes(com)

    def announce_user_change(self, user, allowme=False, what=None):
        """ Report a modified user to plugins and subsystems """

        if allowme == False and user == self.myself:
            return

        if self.community_gui != None:
            self.community_gui.user_changes(user, what)

        for plugin in get_plugins():
            plugin.user_changes(user, what)

    def announce_user(self, user):
        """ Report a new user to plugins and subsystems """

        if user == self.myself:
            self.notify.notify('Announce bug, not announcing myself')
            return

        self.activeusers[user] = None

        if get_debug_mode() or user.get('friend'):
            appearsmsg = 'appears'
            hops = user.get('hops')
            if hops != None:
                appearsmsg += ' at %d hops distance' % hops
            self.notify.user_notify(user, appearsmsg)

        if self.community_gui != None:
            self.community_gui.user_appears(user)

        for plugin in get_plugins():
            plugin.user_appears(user)

    def fetch_community_profiles(self, user):
        cnames = []
        versions = []
        for com in self.get_user_communities(user):
            if com.get('name') != DEFAULT_COMMUNITY_NAME:
                cnames.append(com.get('name'))
                versions.append(com.get('v'))
        if len(cnames) == 0:
            return
        request = {'t': 'cprofiles', 'cname': cnames, 'version': versions}
        self.fetcher.fetch(user, PLUGIN_TYPE_COMMUNITY, request, self.got_community_profiles)

    def find_communities(self, name=None, peer=None, public=None):
        """ Search for communities given 3 criteria.

        'name' is the name of a community to search for, or None.
        name == None means all community names.

        'peer' and 'public' have 3 possible values: None, False and True.
        None means both False and True."""
        
        return find_communities(name, peer, public)

    def gen_rpc_hello(self):
        return {'t': TP_HELLO,
                'v': PROXIMATE_PROTOCOL_VERSION,
                'pv': self.myself.get('v'),
                'port': self.myself.get('port'),
                'nick': self.myself.get('nick'),
                'uid': self.myuid,
               }

    def gen_rpc_bye(self):
        return bencode({'t': TP_QUIT, 'uid': self.myuid})

    def get_community_dir(self, community):
        return get_community_dir(community)

    def get_community_members(self, community):
        """ Get users belonging to the community """

        if not community.get('peer'):
            members = self.personal_community_members(community)
            return filter(lambda user: user.is_present(), members)

        users = self.activeusers.keys()
        cname = community.get('name')
        return filter(lambda user: cname in user.get('communities'), users)

    def get_default_community(self):
        return self.get_ordinary_community(DEFAULT_COMMUNITY_NAME)

    def get_friend_community(self):
        l = self.find_communities(FRIENDS_COMMUNITY_NAME, peer=False, public=False)
        assert(len(l) <= 1)
        if len(l) == 0:
            return None
        return l[0]

    def get_friends(self):
        return self.get_friend_community().get('members')

    def get_myself(self):
        return self.myself

    def get_myuid(self):
        return self.myuid

    def get_network_state(self, network):
        assert(network == self.IP_NETWORK)
        if network == self.IP_NETWORK:
            return self.ipactive
        return False

    def get_ordinary_community(self, cname):
        return get_ordinary_community(cname)

    def get_user(self, uid):
        return get_user(uid)

    def get_user_communities(self, user):
        """ Get list of peer communities the user is member of. """

        communities = []
        for cname in user.get('communities'):
            community = self.get_ordinary_community(cname)
            if community != None:
                communities.append(community)
        return communities

    def get_user_dir(self, user=None):
        """ If user == None, use myself """

        assert(user == None or isinstance(user, User))
        if user == None:
            user = self.myself
        return get_user_dir(user)

    def get_users(self, active):
        if active:
            return self.activeusers.keys()
        else:
            return get_users()

    def got_community_profiles(self, user, reply, ctx):
        if reply == None:
            return

        validator = {
            'cname': [ZERO_OR_MORE, str],
            'profile': [ZERO_OR_MORE, {}]
           }
        if not validate(validator, reply):
            warning('Invalid community profiles reply\n' % str(reply))
            return

        communities = self.get_user_communities(user)

        for (cname, profile) in zip(reply['cname'], reply['profile']):
            if cname == DEFAULT_COMMUNITY_NAME:
                continue
            com = self.get_ordinary_community(cname)
            if com in communities:
                self.update_community_profile(com, user, profile)
                communities.remove(com)

        # Do icon requests for the rest of communities
        for com in communities:
            if com.get('name') != DEFAULT_COMMUNITY_NAME:
                self.request_com_icon(user, com)

    def got_user_profile(self, user, reply, ctx):
        """ This is called when other person's profile has been received """

        user.inprogress = False
        if reply == None:
            return
        profile = reply.get('uprofile')
        if profile == None:
            warning('Invalid user profile: %s\n' % str(reply))
            return
        uid = profile.get('uid')
        if not valid_uid(uid):
            warning('Invalid uid: %s\n' % str(uid))
            return
        if uid == self.myuid or uid != user.get('uid'):
            warning('uid treason detected. Message from %s: %s\n' % (user.get('uid'), str(profile)))
            return
        oldstatus = (user.get('status'), user.get('status_icon'))
        if not user.unserialize(profile):
            warning('Invalid user profile: %s\n' % str(profile))
            return

        # Now we know the profile is valid
        create_user_communities(user)
        self.announce_user_change(user)
        self.save_user(user)

        if oldstatus != (user.get('status'), user.get('status_icon')):
            self.show_status_change(user)

        # The user profile is now up-to-date. Now we can fetch everything else.
        self.request_user_icon(user)
        self.fetch_community_profiles(user)

    def handle_icon_push(self, user, request):
        """ This is called when is received. Save the icon image. """

        validator = {'icon': str,
                     'iconid': str,
                     'version': lambda i: is_unsigned_int('version', i)
                    }
        if not validate(validator, request):
            return None

        icon = request['icon']
        iconid = request['iconid']

        if iconid == 'user':
            if user.get('faceversion') != request['version']:
                # This is an outdated version of the icon..
                return None
            if icon == '':
                # if we got an empty string, user removed the icon
                # giving None to save_face removes the picture
                delete_face(user)
            elif not save_face(user, icon):
                warning('Could not save face for %s: %d bytes\n' % (user.tag(), len(icon)))
                return None
            user.set('myfaceversion', request['version'])
            self.announce_user_change(user, what=(PROFILE_ICON_CHANGED, None))

        elif iconid.startswith('c:'):
            cname = iconid[2:]
            if cname == DEFAULT_COMMUNITY_NAME:
                return None
            com = self.get_ordinary_community(cname)
            if com == None:
                return None
            if com.get('iconversion') != request['version']:
                # This is an outdated version of the icon..
                return None
            if com.get('iconlocked'):
                return None
            if icon == '':
                delete_community_icon(com)
            elif not save_community_icon(com, icon):
                warning('Failed to update community icon: %s\n' % cname)
                return None
            com.set('myiconversion', request['version'])
            self.announce_community_change(com)
        return None

    def handle_community_profile_fetch(self, user, request):
        cname = request.get('cname')
        if type(cname) != str:
            warning('Invalid community profile fetch\n' % str(request))
            return None
        community = self.get_ordinary_community(cname)
        if community == None:
            return None
        return {'cprofile': community.serialize()}

    def handle_community_profiles_fetch(self, user, request):
        validator = {
            'cname': [ZERO_OR_MORE, str],
            'version': [ZERO_OR_MORE, lambda i: is_unsigned_int('version', i)]
           }
        if not validate(validator, request):
            warning('Invalid community profiles fetch\n' % str(request))
            return None

        cnames = []
        profiles = []
        for (cname, version) in zip(request['cname'], request['version']):
            com = self.get_ordinary_community(cname)
            if com == None:
                continue
            if version < com.get('v'):
                cnames.append(cname)
                profiles.append(com.serialize())
                debug('Sending %s community profile to %s\n' %
                    (com.get('name'), user.get('nick')))
        return {'cname': cnames, 'profile': profiles}

    def handle_request(self, user, request):
        handler = self.fetchhandlers.get(request['t'])
        if handler == None:
            warning('Community not handling request: %s\n' % str(request))
            return None
        return handler(user, request)

    def handle_hello(self, user, hello):
        self.remoteusers[user] = 0
        self.got_hello(hello, None)
        return {}

    def handle_invite_community(self, user, request):
        cname = request.get('cname')
        if cname == None:
            return None
        community = self.get_ordinary_community(cname)
        if community == None:
            warning('Got invite to unknown community: %s\n' % cname)
            return None
        if community in self.get_user_communities(self.myself):
            warning('Got invite to community I am already in: %s\n' % cname)
            return None
        self.notify.notify_with_response('%s invited you to community %s. Join the community?' %
                                         (user.tag(), community.get('name')), \
                                         self.invite_response, community)
        return {}

    def invite_response(self, response, msg, community):
        if response == self.notify.RESPONSE_ACTIVATED:
            self.join_community(community)
            return True
        return False

    def handle_icon_request(self, user, request):
        iconid = request.get('iconid')
        if iconid == None or type(iconid) != str:
            return None

        debug('Icon request from %s: %s\n' % (user.get('nick'), iconid))

        if iconid == 'user':
            icon = read_file_contents(seek_face_name(self.myself))
            version = self.myself.get('faceversion')
            limiter = self.iconfetchlimiters['user']

        elif iconid.startswith('c:'):
            cname = iconid[2:]
            if not valid_community(cname):
                return None
            if cname not in self.myself.get('communities'):
                return None
            com = self.get_ordinary_community(cname)
            if com == None:
                return None
            if com.get('myiconversion') != com.get('iconversion'):
                # Do not reply with a old version of the icon!
                return
            icon = read_file_contents(seek_community_icon_name(com))
            version = com.get('iconversion')
            limiter = self.iconfetchlimiters.get(iconid)
            if limiter == None:
                limiter = Rate_Limiter(ICON_PUSH_INTERVAL)
                self.iconfetchlimiters[iconid] = limiter
        else:
            return None

        if icon == None:
            icon = ''
        if version == None:
            version = 0

        request = {'t': 'iconpush', 'iconid': iconid, 'icon': icon, 'version': version}

        if normal_traffic_mode():
            self.fetcher.fetch(user, PLUGIN_TYPE_COMMUNITY, request, None, ack=False)
        elif limiter == None or limiter.check():
            self.fetcher.fetch_community(self.get_default_community(), PLUGIN_TYPE_COMMUNITY, request, None, ack=False)

        return {}

    def handle_user_profile_fetch(self, user, request):
        return {'uprofile': self.myself.serialize()}

    def is_blacklisted(self, user):
        return self.blacklist.has_key(user)

    def is_me(self, user):
        return user == self.myself

    def is_member(self, user, com, allowtemporary=True):
        """ Test if a user belongs to a community """
        if user == self.myself and com.get('peer') == False:
            return True
        return user.in_community(com, allowtemporary=allowtemporary)

    def is_my_friend(self, user):
        assert(isinstance(user, User))
        return user.get('uid') in self.get_friends()

    def invite_member(self, com, user, cb):
        """ Invite user to a peer community. """

        request = {'t': 'cinvite', 'cname': com.get('name')}
        return self.fetcher.fetch(user, PLUGIN_TYPE_COMMUNITY, request, self.invite_sent, cb, retries=1)

    def invite_sent(self, user, reply, cb):
        success = (reply != None)
        cb(success)

    def join_community(self, community, temporary=False):
        """ Join to a peer community. """

        if not community.get('peer'):
            warning('Can not join to personal communities\n')
            return False
        self.myself.join_community(community, temporary)
        self.announce_user_change(self.myself, allowme=True)
        self.notify.notify('Joined to community %s' % community.get('name'))
        return True

    def leave_community(self, community):
        """ Leave a peer community """

        if not community.get('peer'):
            warning('Can not leave a personal community\n')
            return False
        self.myself.leave_community(community)
        self.announce_user_change(self.myself, allowme=True)
        self.notify.notify('Left community %s' % community.get('name'))
        return True

    def log_users(self, t, ctx):
        users = {}
        for user in self.activeusers.keys():
            d = {}
            for attr, val in user.d.items():
                if attr in ['uid', 'v', 'fscounter', 'faceversion', 'status_icon']:
                    continue
                if val == None:
                    continue
                ma = user.metaattributes.get(attr)
                if ma == None or ma.public == False:
                    continue
                if type(val) == list or type(val) == str:
                    x = len(val)
                else:
                    x = 1
                d[attr] = x
            users[user.get('uid')] = d

    def delete_personal_community(self, community):
        # Don't delete friends community
        if community.get('peer') or community == self.get_friend_community():
            return False
        for uid in community.get('members'):
            self.remove_member(community, self.get_user(uid))
        delete_community(community)
        self.announce_user_change(self.myself, allowme=True)
        return True

    def request_user_icon(self, user):
        if user.get('myfaceversion') != user.get('faceversion') and \
           len(self.activeusers) < MAX_ICON_ACTIVE:
            request = {'t': 'iconrequest', 'iconid': 'user'}
            self.fetcher.fetch(user, PLUGIN_TYPE_COMMUNITY, request, None, ack=False)

    def request_com_icon(self, user, com):
        if com.get('myiconversion') != com.get('iconversion') and \
           not com.get('iconlocked') and len(self.activeusers) < MAX_ICON_ACTIVE:
            iconid = 'c:' + com.get('name')
            request = {'t': 'iconrequest', 'iconid': iconid}
            self.fetcher.fetch(user, PLUGIN_TYPE_COMMUNITY, request, None, com, ack=False)

    def remote_discovery(self):
        """ remote discovery keeps remote connections open in each possible
            directions to bypass one-sided firewalls. """

        if self.get_network_state(self.IP_NETWORK) == False:
            return
        hello = None
        benhello = None
        for user in self.remoteusers:
            counter = self.remoteusers[user]
            if self.activeusers.has_key(user):
                # Hello period is 15s
                self.remoteusers[user] = (counter + 1) % 3
                if counter != 0:
                    continue
                if hello == None:
                    hello = self.gen_rpc_hello()
                self.fetcher.fetch(user, PLUGIN_TYPE_COMMUNITY, hello, None)
                continue

            addresses = user.get('remotes')
            if addresses == None or len(addresses) == 0:
                continue

            # Try connection period is 30s -> 2880 connections/day
            self.remoteusers[user] = (counter + 1) % 6
            if counter != 0:
                continue

            if benhello == None:
                if hello == None:
                    hello = self.gen_rpc_hello()
                benhello = bencode(hello)

            for address in addresses:
                port = address[1]
                if port == None:
                    port = DEFAULT_PROXIMATE_PORT
                Hello_Client((address[0], port), benhello)

    def periodic_event(self, t, ctx):
        if self.udp_send:
            self.broadcast(bencode(self.gen_rpc_hello()))

        for user in self.activeusers.keys():
            if user.timeout():
                self.denounce_user(user)

        self.remote_discovery()

        self.req_counter += 1
        if self.req_counter >= REQUEST_INTERVAL:
            for user in self.activeusers.keys():
                self.request_user_icon(user)
            self.req_counter = 0

        if self.myself.dirty:
            self.save_user(self.myself)
        return True

    def personal_community_members(self, community):
        assert(community.get('peer') == False)
        members = community.get('members')
        assert(type(members) == list)
        return filter(lambda u: u != None, map(lambda uid: self.get_user(uid), members))

    def ready(self):
        global community
        community = self
        self.fetcher = get_plugin_by_type(PLUGIN_TYPE_FETCHER)
        self.notify = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)
        self.net = get_plugin_by_type(PLUGIN_TYPE_NETWORK_CONTROL)

        self.fetcher.register_handler(PLUGIN_TYPE_COMMUNITY, self.handle_request, 'community fetch')

        settings = get_plugin_by_type(PLUGIN_TYPE_SETTINGS)
        self.default_rpc_port_setting = settings.register('community.rpc_port', int, 'TCP listening port; 0 means a random port.\nTakes effect after restart', default=0, validator=valid_port)
        self.listener_port_setting = settings.register('community.listener_port', int, 'Peer discovery (UDP) listening port.\nTakes effect after restart', default=DEFAULT_PROXIMATE_PORT, validator=valid_port)

        # The command line setting has the highest priority, then comes
        # the config file port, and random port has the least priority.
        if self.activeport != None:
            self.myself.set('port', self.activeport)
        else:
            port = self.default_rpc_port_setting.value
            if port != 0:
                self.myself.set('port', port)
            else:
                self.gen_port()

        if self.udp_listen:
            self.create_udp_listener()

        sch = get_plugin_by_type(PLUGIN_TYPE_SCHEDULER)
        sch.call_periodic(TP_SCAN_INTERVAL * sch.SECOND, self.periodic_event, callnow=True)

        # Set periodic active user logging
        sch.call_periodic(15 * 60 * sch.SECOND, self.log_users)

    def remove_friend(self, user):
        assert(isinstance(user, User))
        self.get_friend_community().remove_member(user)
        self.announce_user_change(user)

    def remove_member(self, com, user):
        """ Remove member from a personal community. """

        assert(isinstance(com, Community))
        assert(isinstance(user, User))

        if com.get('peer'):
            warning('Can not remove member from peer community\n')
            return False

        if com == self.blistcom:
            self.blacklist.pop(user, None)

        com.remove_member(user)
        self.save_communities([com])
        self.announce_user_change(user, allowme=True)
        self.notify.notify('%s removed from community %s' % (user.tag(), com.get('name')))
        return True

    def get_rpc_port(self):
        return self.myself.get('port')

    def gen_port(self):
        port = randint(TP_MIN_PORT, TP_MAX_PORT)
        self.myself.set('port', port)

    def got_rpc_msg(self, data, address):
        if not self.ipactive:
            return

        d = fmt_bdecode({'t': str}, data)
        if d == None:
            return

        if d['t'] == TP_HELLO:
            self.got_hello(d, address)
        elif d['t'] == TP_QUIT:
            self.got_bye(d, address)
        else:
            info('Invalid RPC hello type: %s\n' % d['t'])

    def got_hello(self, d, address):
        """ Check validity of Proximate hello, and register the other party. """

        validator = {
            'v': valid_protocol_version,
            'pv': lambda x: type(x) == int and x >= 0,
            'port': valid_port,
            'nick': valid_nick,
            'uid': lambda s: valid_uid(s) and s != self.myuid,
           }
        if not validate(validator, d):
            if type(d) != dict or d.get('uid') != self.myuid:
                info('Rejecting signature: %s\n' % str(d))
            return

        updatelist = [('nick', d['nick']), ('protocolversion', d['v'])]

        if address != None:
            ip = address[0]
        else:
            ip = None
        self.add_or_update_user(d['uid'], updatelist, d['pv'], ip, d['port'])

    def got_bye(self, d, address):
        """ User quit, denounce """

        validator = {
            'uid': lambda s: valid_uid(s) and s != self.myuid,
           }
        if not validate(validator, d):
            return

        user = self.safe_get_user(d.get('uid'), address[0])
        if user == None:
            info('Rejecting quit message from uid %s\n' % d.get('uid'))
        else:
            self.denounce_user(user)

    def safe_get_user(self, uid, ip):
        if valid_uid(uid) == False or uid == self.myuid:
            return None
        user = self.get_user(uid)
        if user == None:
            # Create a minimal user object for the peer so that we can reply
            return create_user(uid)
        oldip = user.get('ip')
        if ip != None and oldip != None and ip != oldip:
            return None
        if self.is_blacklisted(user):
            return None
        return user

    def save_communities(self, communities):
        save_communities(communities)

    def save_user(self, user):
        save_user(user)

    def set_community_icon(self, com, icon_fname):
        if icon_fname == None:
            delete_community_icon(com)
        else:
            icon = read_file_contents(icon_fname)
            if icon == None:
                warning('Can not set community icon from %s\n' % icon_fname)
                return False
            if not save_community_icon(com, icon):
                warning('Could not save community icon from %s\n' % icon_fname)
                return False

        # New icon version so other users will be notified. Random number
        # because this is a distributed system
        version = randint(0, 1 << 32 - 1)
        com.set('iconversion', version)
        com.set('myiconversion', version)

        self.announce_community_change(com)
        return True

    def set_network_state(self, network, state):
        """ set_network_state() is used to disable networks """

        assert(network == self.IP_NETWORK)

        if self.ipactive == state:
            return
        self.ipactive = state

        if state == False:
            # Close IP network: rpc.py will react indirectly
            msg = 'IP networking disabled'
            self.fetcher.close_ip_connections(msg)
            self.notify.notify(msg + ' (this is a fake disable)', highpri=True)
        else:
            self.notify.notify('IP networking enabled', highpri=True)

    def set_my_face(self, face_fname):
        """ Set new profile picture for given user. Should be myself! """

        if not face_fname:
            delete_face(self.myself)
        else:
            face = read_file_contents(face_fname)
            if face == None:
                warning('Can not set user face from %s\n' % face_fname)
                return False
            if not save_face(self.myself, face):
                warning('Could not save user face from %s\n' % face_fname)
                return False

        if self.myself.get('faceversion') == None:
            self.myself.set('faceversion', 0)
        else:
            self.myself.set('faceversion', self.myself.get('faceversion') + 1)

        self.announce_user_change(self.myself, allowme=True)
        return True

    def udp_listener_read(self, rfd, condition):
        """ Receive packet from listening socket and check Proximate hello """

        try:
            data, address = rfd.recvfrom(1024)
        except socket.error, (errno, strerror):
            ret = (errno == EAGAIN or errno == EINTR)
            if not ret:
                warning('WLAN UDP Listen: Socket error(%s): %s\n' % (errno, strerror))
            return ret

        self.got_rpc_msg(data, address)
        return True

    def update_community_profile(self, com, user, profile):
        if com.get('name') != profile.get('name'):
            warning('Name mismatch in community profile: %s vs %s\n' % (com.get('name'), str(profile)))
            return

        if not com.unserialize(profile):
            warning('At least part of the community profile failed: %s\n' % profile)
            return

        self.announce_community_change(com)
        self.save_communities([com])
        self.request_com_icon(user, com)

    def get_user_personal_communities(self, user):
        uid = user.get('uid')
        coms = []
        for com in self.find_communities(peer=False):
            members = com.get('members')
            assert(type(members) == list)
            if uid in members:
                coms.append(com)
        return coms

    def show_status_change(self, user):
        status = user.get('status')
        status_icon = user.get('status_icon')
        text = 'changed status to '
        if status:
            text += status
        if status_icon:
            if status:
                text += ' (%s)' % status_icon
            else:
                text += status_icon
        self.notify.user_notify(user, text)

class Hello_Client:
    def __init__(self, address, benhello):
        self.address = address
        self.q = TCP_Queue(self.msghandler)
        if not self.q.connect(address, TP_CONNECT_TIMEOUT):
            return
        prefix = TP_HELLO + '\n'
        self.q.write(prefix, writelength=False)
        self.q.write(benhello)
        self.q.set_timeout(TP_CONNECT_TIMEOUT)

    def msghandler(self, q, data, ctx):
        community.got_rpc_msg(data, self.address)
        return False

class Hello_Server:
    def __init__(self, address, sock, data):
        self.q = TCP_Queue(self.msghandler)
        self.q.set_timeout(TP_CONNECT_TIMEOUT)
        self.address = address
        self.q.append_input(data)
        self.q.initialize(sock)

    def msghandler(self, q, benhello, ctx):
        community.got_rpc_msg(benhello, self.address)
        self.q.write(bencode(community.gen_rpc_hello()))
        self.q.close_after_send()
        return True

def init(options):
    Community_Plugin(options)
