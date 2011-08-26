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
from meta import Meta

class Plugin_State(Meta):
    def __init__(self):
        # metaattributes is not a class variable in plugin specific state
        self.metaattributes = {}
        self.base_init()
