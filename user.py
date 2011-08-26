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

from ioutils import valid_ip
from meta import Meta, Meta_Attribute, validate_list, is_unsigned_int, \
     publicstring, publicunsignedint, privatestring, privateunsignedint
from proximateprotocol import valid_cid, valid_community, \
     valid_nick, valid_status, TP_NICK_DEFAULT, \
     valid_port, valid_protocol_version, valid_uid, \
     DEFAULT_COMMUNITY_NAME, FRIENDS_COMMUNITY_NAME, \
     MAX_USER_INACTIVITY_TIME, PROXIMATE_PROTOCOL_VERSION
from utils import relative_time_string

# Meta attributes are defined as class variables. That is, each instance
# of User shares the same metaattributes dictionary.
userattributes = {}

# Public attributes
for pubkey in ['age', 'birth_date', 'city', 'country', 'description', 'email', 'gender', 'languages', 'name', 'occupation', 'phone_numbers', 'state', 'status', 'www']:
    userattributes[pubkey] = publicstring()

def community_filter(user, value):
    communities = []
    tempcommunities = user.get('tempcommunities')
    for name in value:
        if name not in tempcommunities:
            communities.append(name)
    return communities

userattributes['communities'] = Meta_Attribute(list, public=True, is_valid=lambda n, v: validate_list(v, valid_community), default=[DEFAULT_COMMUNITY_NAME])
userattributes['communities'].is_required()
userattributes['communities'].process_before_save(community_filter)

userattributes['faceversion'] = Meta_Attribute(int, public=True, is_valid=is_unsigned_int, default=0)
userattributes['fscounter'] = Meta_Attribute(int, public=True, is_valid=is_unsigned_int, default=0)
userattributes['fscounter'].is_required()

userattributes['nick'] = Meta_Attribute(str, public=True, is_valid=lambda n, v: valid_nick(v), default=TP_NICK_DEFAULT)
userattributes['nick'].is_required()
userattributes['status_icon'] = Meta_Attribute(str, public=True, is_valid=lambda n, v: valid_status(v))
userattributes['uid'] = Meta_Attribute(str, public=True, is_valid=lambda n, v: valid_uid(v))
userattributes['uid'].is_required()

# Private attributes
userattributes['key_fname'] = privatestring()
userattributes['privcommunities'] = Meta_Attribute(list, public=False, is_valid=lambda n, v: type(v) == list and validate_list(v, valid_cid), default=[])
userattributes['remotes'] = Meta_Attribute(list, public=False)
userattributes['friend'] = Meta_Attribute(bool, public=False, save=True, default=False)
userattributes['myfaceversion'] = privateunsignedint()

# Private non-saved attributes
userattributes['ip'] = Meta_Attribute(str, public=False, save=False, is_valid=lambda n, v: valid_ip(v))
userattributes['port'] = Meta_Attribute(int, public=False, save=False, is_valid=lambda n, v: valid_port(v))
userattributes['protocolversion'] = Meta_Attribute(int, public=False, save=False, is_valid=lambda n, v: valid_protocol_version(v), default=PROXIMATE_PROTOCOL_VERSION)

userattributes['tempcommunities'] = Meta_Attribute(list, public=False, save=False, is_valid=lambda n, v: validate_list(v, valid_community), default=[])

userattributes['timeout'] = Meta_Attribute(int, public=False, save=False, is_valid=is_unsigned_int)
userattributes['hops'] = Meta_Attribute(int, public=False, save=False, is_valid=is_unsigned_int)
userattributes['hophistory'] = Meta_Attribute(list, public=False, save=False)

class User(Meta):
    def __init__(self):
        self.metaattributes = userattributes
        self.base_init()

        # Initialize per session information
        self.present = False
        self.inprogress = False

    def force_profile_update(self):
        """ This will cause community plugin to refetch the profile next
            the user announces its profile version. """

        version = self.get('v') - 1
        if version < 0:
            version = 4096                 # hack: arbitrary large value :-)
        self.set('faceversion', None)
        self.d['v'] = version

    def in_community(self, com, allowtemporary=True):
        """ Return True iff the user belongs to a given community.
            If allowtemporary is True, only real membership counts. Otherwise
            True is returned even for a temporary membership.

            Note, this can not be used to test if I belong to a personal
            community. The function will return False. """

        name = com.get('name')
        if com.get('peer'):
            if name not in self.get('communities'):
                return False
            if allowtemporary == False and name in self.get('tempcommunities'):
                return False
            return True
        else:
            return self.get('uid') in com.get('members')

    def is_present(self):
        return self.present

    def join_community(self, community, temporary):
        if community.get('peer') and community.get('public'):
            name = community.get('name')
            # be defensive, check against duplicate
            if temporary:
                if name not in self.get('communities'):
                    self.add_list_item('tempcommunities', name, valid_community)
            else:
                self.remove_list_item('tempcommunities', name)

            self.add_list_item('communities', name, valid_community)
        else:
            cid = community.get('cid')
            self.add_list_item('privcommunities', cid, valid_cid)

    def leave_community(self, community):
        """ Note, can not leave the default community """
        name = community.get('name')
        if name == DEFAULT_COMMUNITY_NAME:
            return
        if community.get('peer') and community.get('public'):
            self.remove_list_item('communities', name)
            self.remove_list_item('tempcommunities', name)
        else:
            self.remove_list_item('privcommunities', community.get('cid'))

    def update_presence(self, present):
        """ Set user's presence. present == True if user is present now, and
        present == False is not present now.

        Returns True iff user appears. """

        if present:
            # Do not update profile version number
            self.d['timeout'] = int(time.time() + MAX_USER_INACTIVITY_TIME)
        else:
            self.log_disappear()

        # Return True iff user appears
        appears = (present and self.present == False)
        self.present = present
        return appears

    def log_disappear(self):
        l = self.get('disappearances')
        if l == None:
            l = []
        l.insert(0, time.time())
        while len(l) > 3:
            l.pop()
        self.set('disappearances', l)

    def tag(self):
        s = self.get('nick')
        if self.get('name'):
            s += ' (%s)' %(self.get('name'))
        return s

    def timeout(self):
        timeout = self.get('timeout')
        return timeout == None or int(time.time()) >= timeout

    def log(self):
        log = []
        l = self.get('disappearances')
        if l != None:
            for t in l:
                log.append((relative_time_string(t), ''))
        return log
