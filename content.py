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
import os

from meta import Meta, Meta_Attribute, publicstring
from support import warning

contentattributes = {}

# Public attributes
for pubkey in ['author', 'communities', 'description', 'communities', 'keywords', 'timestart', 'timeend', 'title', 'type', 'year']:
    contentattributes[pubkey] = publicstring()

# Private non-saveable attributes 
contentattributes['fname'] = Meta_Attribute(str, public=False, save=False)

class Content_Meta(Meta):
    metasection = 'meta'

    def __init__(self):
        self.metaattributes = contentattributes
        self.base_init()

    def meta_name(self, fname):
        dname = os.path.dirname(fname)
        bname = os.path.basename(fname)
        return os.path.join(dname, '.%s.proximatemeta' %(bname))

    def read_meta(self, fname):
        metaname = self.meta_name(fname)
        try:
            f = open(metaname, 'r')
        except IOError:
            return False
        metadata = f.read()
        f.close()
        return self.read_meta_from_string(metadata, fname=fname)

    def import_meta(self, d, fname=None):
        if not self.unserialize(d):
            warning('Invalid content meta: %s\n' %(str(d)))
            return False
        return fname == None or self.set('fname', fname)

    def read_meta_from_string(self, metadata, fname=None):
        if not self.read_ini_file(metadata):
            return False
        # Remember filename for searching
        return self.set('fname', fname)

    def save_meta(self, fname):
        self.save_to_ini_file(self.meta_name(fname))
