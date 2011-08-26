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
import string

PROXIMATE_PROTOCOL_VERSION = 0

PLUGIN_TYPE_COMMUNITY = 'community'
PLUGIN_TYPE_FETCHER = 'fetcher'
PLUGIN_TYPE_TCP_FETCHER = 'tcpfetcher'
PLUGIN_TYPE_UDP_FETCHER = 'udpfetcher'
PLUGIN_TYPE_FILE_SHARING = 'filesharing'
PLUGIN_TYPE_SEND_FILE = 'sendfile'
PLUGIN_TYPE_MESSAGING = 'messaging'
PLUGIN_TYPE_STATE = 'state'
PLUGIN_TYPE_KEY_MANAGEMENT = 'keymanagement'
PLUGIN_TYPE_NOTIFICATION = 'notification'
PLUGIN_TYPE_NETWORK_CONTROL = 'networkcontrol'
PLUGIN_TYPE_SCHEDULER = 'scheduler'
PLUGIN_TYPE_FILE_TRANSFER = 'filetransfer'
PLUGIN_TYPE_MESSAGE_BOARD = 'messageboard'
PLUGIN_TYPE_USER_PRESENCE = 'userpresence'
PLUGIN_TYPE_VIBRA = 'vibra'
PLUGIN_TYPE_SETTINGS = 'settings'

TP_MIN_PORT = 1024
TP_MAX_PORT = 65535
DEFAULT_PROXIMATE_PORT = 10651
PORT_RETRIES = 13

DEFAULT_COMMUNITY_NAME = 'Proximate'
FRIENDS_COMMUNITY_NAME = 'Friends'
BLACKLIST_COMMUNITY_NAME = 'Blacklist'

# The default interval between scanning in seconds
TP_SCAN_INTERVAL = 5

TP_NICK_MAX_LEN = 32
TP_NICK_DEFAULT = 'anonymous'

# Maximum inactivity time (seconds) for user to be considered to be present
MAX_USER_INACTIVITY_TIME = 60

# Maximum number of bytes for a face picture
TP_MAX_FACE_SIZE = 8192

# Preferred number of bytes for a face picture
TP_FACE_SIZE = 4096

# Maximum width and height for a face picture
MAX_FACE_DIMENSION = 128

TP_UID_BITS = 64           # Number of bits in user ID

TP_COMMUNITY_MAX_LEN = 64

# The default timeout for connecting sockets
TP_CONNECT_TIMEOUT = 20

# The default timeout for protocol commands
TP_PROTOCOL_TIMEOUT = 20

# The default timeout for fetcher requests
TP_FETCH_TIMEOUT = 60

# Maximum number of characters in RPC command name / fetcher rtype
TP_MAX_CMD_NAME_LEN = 32

TP_MAX_NAME_LEN = 255

TP_MAX_TRANSFER = 4096
TP_MAX_RECORD_SIZE = 1024 * 1024

TP_MAX_HELLO_SIZE = 512

# RPC commands
TP_FETCH_RECORDS = 'PROXIMATE_FETCH'
TP_HELLO = 'PROXIMATE_HELLO'
TP_QUIT = 'PROXIMATE_QUIT'
TP_SEND_FILE = 'PROXIMATE_SEND_FILE'
TP_GET_FILE = 'PROXIMATE_GET_FILE'

# An RPC handler may do 3 things for a TCP message that is received in the
# RPC handler:
RPC_MORE_DATA = 0                  # 1. Wait for more data before handling it
RPC_CLOSE     = 1                  # 2. Close the connection
# 3. The handler gets the ownership of the socket, RPC handler won't close it
# and will not wake for its IO anymore.
RPC_RELEASE   = 2

# List of possible user statuses. The normal state should be the first value.
USER_STATUS_LIST = ['normal', 'happy', 'sad', 'bored', 'smiling', 'crying']

FS_PURPOSE_SHARE = 'fs'

# share types
SHARE_BOGUS = 'bogus'
SHARE_DIR = 'dir'
SHARE_FILE = 'file'

# 32 hops is probably too much
FS_REPLICATE_DEFAULT_TTL = 0
FS_REPLICATE_MAX_TTL = 8
FS_REPLICATE_MAX_SIZE = 2048

FS_REPLICATE_STORE_MAX = 512

FS_MAX_SHARES_TO_CHECK = 64

# FS GID == filesharing's global sharemeta id
FS_GID_LIMIT = pow(2, 64)

PROFILE_ICON_CHANGED = 0
HOP_COUNT_CHANGED = 1

def valid_community(community):
    if type(community) != str:
        return False
    if len(community) > TP_COMMUNITY_MAX_LEN or len(community) == 0:
        return False
    if community.find('\n') >= 0 or community.find(',') >= 0:
        return False
    return True

valid_fs_gid = lambda x: (type(x) == int or type(x) == long) and x >= 0 and x < FS_GID_LIMIT

def valid_nick(nick):
    if type(nick) != str:
        return False
    if len(nick) > TP_NICK_MAX_LEN or len(nick) == 0:
        return False
    if nick.find('\n') >= 0:
        return False
    return True

def valid_port(port):
    if type(port) != int:
        return False
    return port >= TP_MIN_PORT and port <= TP_MAX_PORT

def valid_protocol_version(version):
    if type(version) != int:
        return False
    return version >= 0

def valid_receive_name(fn):
    if type(fn) != str:
        return False

    fnlen = len(fn)
    if fnlen == 0 or fnlen > TP_MAX_NAME_LEN:
        return False

    if fn.find('/') >= 0 or fn.find('\n') >= 0 or fn[0] == '.':
        return False

    return True

def valid_cid(cid):
    if type(cid) != int:
        return False
    return cid >= 0

def valid_uid(uid, bits = TP_UID_BITS):
    if type(uid) != str:
        return False

    if uid.islower() == False:
        return False

    l = list(uid)
    if len(l) != (bits / 4):
        return False

    for c in l:
        if c not in string.hexdigits:
            return False

    return True

def valid_status(status):
    if type(status) != str:
        return False
    return status in USER_STATUS_LIST
