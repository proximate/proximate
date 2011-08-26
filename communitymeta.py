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
from time import time

from meta import Meta, Meta_Attribute, validate_list, privatebool, \
     publicstring, publicunsignedint, privateunsignedint, privatestringlist, \
     is_unsigned_int
from proximateprotocol import valid_community, valid_uid

comattrs = {}

# Public attributes
for pubkey in ['creator', 'description', 'keywords', 'timestart', 'timeend', 'location', 'www']:
    comattrs[pubkey] = publicstring()

comattrs['creatoruid'] = Meta_Attribute(str, public=True, is_valid=lambda n, v: valid_uid(v))

comattrs['iconversion'] = Meta_Attribute(int, public=True, is_valid=is_unsigned_int, default=0)

comattrs['name'] = Meta_Attribute(str, public=True, is_valid=lambda n, v: valid_community(v))
comattrs['name'].is_required()

# Private attributes
comattrs['cid'] = privateunsignedint()
comattrs['invisible'] = privatebool(default=False)
comattrs['members'] = Meta_Attribute(list, public=False, is_valid=lambda n, v: validate_list(v, valid_uid), default=[])
comattrs['keys'] = privatestringlist()
comattrs['peer'] = Meta_Attribute(bool, public=False, default=True)
comattrs['public'] = Meta_Attribute(bool, public=False, default=True)
comattrs['iconlocked'] = Meta_Attribute(bool, public=False, default=False)
comattrs['myiconversion'] = privateunsignedint()

# Private non-saved
# Nothing atm

class Community(Meta):
    """ There are two very important properties in a community.
    Community is a 'peer community' iff peer attribute is true. This
    means anyone may belong to the community by simply stating it.
    If peer is false, the user decides who belongs to it. In this case,
    it is called a 'personal community'.

    'members' attribute is only used in personal communities.

    Communication is encrypted iff public is false.
    Encrypted community is called a 'private community'.
    Peers with a proper key (in keys attribute) can talk together.

    Note, community names are not unique due to 'peer', 'public' and
    'keys' attributes.
    """

    def __init__(self):
        self.metaattributes = comattrs
        self.base_init()

        self.inprogress = False

    def add_member(self, user):
        self.add_list_item('members', user.get('uid'), valid_uid)

    def is_ordinary(self):
        return self.get('peer') and self.get('public')

    def new_version(self):
        if self.d['v'] < int(time()):
            self.d['v'] = int(time())
        else:
            self.d['v'] += 1

    def read_profile(self, profile):
        if not self.read_python_file(profile):
            return False
        return self.get('cid') != None

    def remove_member(self, user):
        self.remove_list_item('members', user.get('uid'))
