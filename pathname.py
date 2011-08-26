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
# Module for storing paths

from os.path import join, dirname
from support import die

ICON_DIR = 'images/icons'

DEFAULT_USER_ICON = '128px-default_user_icon.png'
DEFAULT_COMMUNITY_ICON = 'default_community_icon.png'
PROXIMATE_COMMUNITY_ICON = '128px-proximate_community_icon.png'
SMALL_KEYS_ICON = 'keys.png'
FRIEND_COMMUNITY_ICON = '128px-friend_community_icon.png'

paths = {DEFAULT_USER_ICON: ICON_DIR, 
         DEFAULT_COMMUNITY_ICON: ICON_DIR, 
         PROXIMATE_COMMUNITY_ICON: ICON_DIR,
         SMALL_KEYS_ICON: ICON_DIR,
         FRIEND_COMMUNITY_ICON: ICON_DIR,
        }

def get_dir(var):
    return join(dirname(__file__), var)

def get_path(var):
    return join(get_dir(paths[var]), var)
