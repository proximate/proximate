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
"""
User and community database management, configfile reading and writing
"""
from copy import deepcopy
import os
import sys

from communitymeta import Community
from ossupport import xmkdir, xremove, xremovedir, xrename
from plugins import Plugin
from pluginstate import Plugin_State
from support import die, warning, info, set_log_file
from proximateprotocol import DEFAULT_COMMUNITY_NAME, DEFAULT_PROXIMATE_PORT, \
     TP_UID_BITS, TP_MAX_FACE_SIZE, \
     valid_uid, PLUGIN_TYPE_STATE, valid_community
from user import User
from utils import check_image, new_integer_key, random_hexdigits, str_to_int

myself = None
users = {}
communities = {}

broadcastports = [DEFAULT_PROXIMATE_PORT]

images_path = None
proximatedir = None

TRAFFIC_NORMAL = 0
TRAFFIC_MINIMAL = 1
TRAFFIC_UPPER_BOUND = 1

trafficmode = TRAFFIC_NORMAL

def add_user(user):
    global myself

    uid = user.get('uid')
    if myself != None and uid == myself.get('uid'):
        warning('Can not store myself again\n')
        return False

    users[uid] = user
    create_user_communities(user)
    return True

def create_user(uid):
    user = User()
    user.set('uid', uid)
    if not create_user_dir(user):
        return None
    add_user(user)
    return user

def create_user_dir(user):
    udir = get_user_dir(user)
    if xmkdir(udir):
        return udir
    return None

def create_community(name):
    global communities
    community = Community()
    cid = new_integer_key(communities)
    community.set('cid', cid)
    community.set('name', name)
    communities[cid] = community
    return community

def create_myself():
    global myself
    assert(myself == None)
    uid = random_hexdigits(TP_UID_BITS)
    myself = create_user(uid)

def create_user_communities(user):
    for cname in user.get('communities'):
        if not valid_community(cname):
            warning('Invalid community: %s\n' %(cname))
            continue
        if get_ordinary_community(cname) == None:
            community = create_community(cname)
            save_communities([community])

def delete_community(community):
    global communities
    communities.pop(community.get('cid'))
    cdir = get_community_dir_name(community)
    if not xremovedir(cdir):
        warning("Unable to remove community directory %s\n" %(cdir))

def delete_face(user):
    xremove(get_face_name(user, legacyname=False))
    xremove(get_face_name(user, legacyname=True))

def delete_community_icon(com):
    xremove(get_community_icon_name(com, legacyname=False))
    xremove(get_community_icon_name(com, legacyname=True))

def find_communities(cname, peer, public):
    l = []
    for community in communities.values():
        if cname != None and community.get('name') != cname:
            continue
        if peer != None and community.get('peer') != peer:
            continue
        if public != None and community.get('public') != public:
            continue
        l.append(community)
    return l

def get_community_dir(community):
    cdir = get_community_dir_name(community)
    if not xmkdir(cdir):
        return None
    return cdir

def get_community_dir_name(community):
    cid = community.get('cid')
    cdir = '%s/c_%d' %(proximatedir, cid)
    return cdir

def get_community_fname(community, fname='profile'):
    cdir = get_community_dir(community)
    if cdir == None:
        return None
    return '%s/%s' %(cdir, fname)

def get_community_icon_name(community, legacyname=False):
    if legacyname:
        return get_community_fname(community, fname='icon')
    else:
        return get_community_fname(community, fname='icon.jpg')

def seek_community_icon_name(community):
    fname = get_community_icon_name(community, legacyname=False)
    if os.path.exists(fname):
        return fname
    return get_community_icon_name(community, legacyname=True)

def get_config_name():
    if proximatedir == None:
        return None
    return proximatedir + '/config'

def get_external_plugin_dir():
    return '%s/plugins' % proximatedir

def get_images_path():
    return images_path

def get_face_name(user, legacyname=False):
    """ XXX: remove legacyname logic after migration period """

    if legacyname:
        return '%s/face' % get_user_dir(user)
    else:
        return '%s/icon.jpg' % get_user_dir(user)

def seek_face_name(user):
    fname = get_face_name(user, legacyname=False)
    if os.path.exists(fname):
        return fname
    return get_face_name(user, legacyname=True)

def get_myself():
    return myself

def get_ordinary_community(cname):
    communities = find_communities(cname, True, True)
    if len(communities) > 0:
        assert(len(communities) == 1)
        return communities[0]
    return None

def get_broadcast_ports():
    """ Returns a list of broadcast ports """
    global broadcastports
    return broadcastports

def normal_traffic_mode():
    """ Returns True iff normal traffic mode """
    return trafficmode == TRAFFIC_NORMAL

def get_user_dir(user=None):
    if user == None:
        user = myself
    uid = user.get('uid')
    return '%s/u_%s' %(proximatedir, uid)

def get_user(uid):
    try:
        user = users[uid]
    except KeyError:
        user = read_user_profile(uid)
        if user == None:
            users[uid] = None
    return user

def get_users():
    return filter(lambda user: user != None, users.values())

def load_external_plugins(options=None, ui=None):
    # Load external plugins, if any
    pdir = get_external_plugin_dir()
    try:
        fnames = os.listdir(pdir)
    except OSError:
        return
    if len(fnames) > 0:
        sys.path.insert(0, pdir)
    imported = {}
    for fname in fnames:
        if not (fname.endswith('.py') or fname.endswith('.pyc')):
            continue
        modulename = fname.rpartition('.')[0]    # Strip file extension
        if modulename in imported:
            continue
        module = __import__(modulename)
        fullpath = os.path.join(pdir, fname)
        try:
            if ui != None:
                module.init_ui(ui)
            else:
                module.init(options)
            imported[modulename] = None
        except TypeError:
            die('external plugin %s failed\n' % fullpath)
        except AttributeError:
            pass

def parse_user_dentry(dentry):
    if not dentry.startswith('u_'):
        return None
    uid = dentry[2:]
    if not valid_uid(uid):
        uid = None
    return uid

def read_communities():
    global communities
    if proximatedir == None:
        warning('No Proximate directory\n')
        return

    # Read community meta datas
    for dentry in os.listdir(proximatedir):
        if not dentry.startswith('c_'):
            continue
        if str_to_int(dentry[2:], None) == None:
            continue
        cdir = '%s/%s' %(proximatedir, dentry)
        if not os.path.isdir(cdir):
            continue
        cfile = '%s/profile' %(cdir)

        community = Community()
        try:
            f = open(cfile, 'r')
        except IOError:
            continue
        profile = f.read()
        f.close()
        if community.read_profile(profile):
            communities[community.get('cid')] = community

    defcom = get_ordinary_community(DEFAULT_COMMUNITY_NAME)
    if defcom == None:
        create_community(DEFAULT_COMMUNITY_NAME)

def save_communities(clist=None):
    if clist == None:
        clist = communities.values()
    for community in clist:
        fname = get_community_fname(community)
        if fname == None:
            warning('Can not save community %s (%s)\n' %(community.get('name'), community.get('cid')))
            continue
        community.save_to_python_file(fname)

        # XXX: remove this logic with get_community_icon_name legacy removal
        newname = get_community_icon_name(community, legacyname=False)
        if not os.path.exists(newname):
            xrename(get_community_icon_name(community, legacyname=True), newname)

def save_image(fname, image):
    if fname == None:
        return False
    basename = os.path.basename(fname)
    tmpname = fname + '.tmp'
    try:
        f = open(tmpname, 'w')
    except IOError, (errno, strerror):
        warning('Can not save face to %s: %s\n' %(tmpname, strerror))
        return False
    f.write(image)
    f.close()

    if not check_image(tmpname):
        xremove(tmpname)
        return False

    if not xrename(tmpname, fname):
        xremove(tmpname)
        warning('Can not rename: %s -> %s\n' %(tmpname, fname))
        return False

    return True

def save_community_icon(com, icon):
    # personal communities can have arbitary large icons because the picture
    # is not sent over network
    if com.get('peer') and len(icon) > TP_MAX_FACE_SIZE:
        warning('Community %s has too large icon picture: %d\n' %(com.get('name'), len(icon)))
        return False
    return save_image(get_community_icon_name(com, legacyname=False), icon)

def save_face(user, face):
    if len(face) > TP_MAX_FACE_SIZE:
        warning('User %s has too long a profile picture: %d\n' %(user.get('nick'), len(face)))
        return False
    return save_image(get_face_name(user, legacyname=False), face)

def set_traffic_mode(mode):
    """ Set mode == TRAFFIC_NORMAL for normal traffic.
        Set mode == TRAFFIC_MINIMAL for minimal traffic. """
    global trafficmode
    if mode < 0 or mode > TRAFFIC_UPPER_BOUND:
        die('Invalid traffic mode %d\n' % mode)
    trafficmode = mode

def read_user_profile(uid):
    userdir = '%s/u_%s' % (proximatedir, uid)
    if not os.path.isdir(userdir):
        return None
    userfile = '%s/profile' % (userdir)

    try:
        f = open(userfile, 'r')
    except IOError:
        return None
    data = f.read()
    f.close()
    user = User()
    if not user.read_python_file(data):
        warning('Failed reading user profile for user %s\n' % (uid))
        return None
    add_user(user)
    return user

def read_users():
    if proximatedir == None:
        warning('No Proximate directory\n')
        return

    for dentry in os.listdir(proximatedir):
        uid = parse_user_dentry(dentry)
        if uid != None:
            read_user_profile(uid)

def save_user(saveuser=None):
    if proximatedir == None:
        warning('Can not write users: no .proximate directory\n')
        return

    if saveuser == None:
        userlist = get_users()
    else:
        userlist = [saveuser]

    for user in userlist:
        userdir = get_user_dir(user)
        if not xmkdir(userdir):
            warning('Can not create directory for %s\n' %(user.get('uid')))
            continue
        fname = '%s/profile' %(userdir)
        user.save_to_python_file(fname)

        # XXX: remove this logic with get_face_name legacy name removal
        newname = get_face_name(user, legacyname=False)
        if not os.path.exists(newname):
            xrename(get_face_name(user, legacyname=True), newname)

class State_Plugin(Plugin):
    def __init__(self, options):
        global images_path, proximatedir, broadcastports

        self.options = options

        self.register_plugin(PLUGIN_TYPE_STATE)

        self.pluginstorage = {}

        home = os.getenv('HOME')
        if home == None:
            die('HOME not defined\n')

        images_path = '%s/MyDocs/.images' %(home)

        if options.proximatedir != None:
            proximatedir = options.proximatedir
        else:
            proximatedir = '%s/.proximate' %(home)
        if not xmkdir(proximatedir):
            die('Can not create a proximate directory: %s\n' %(proximatedir))

        set_log_file('%s/log' %(proximatedir))

        read_communities()
        self.config_read()

        if options.broadcastports != None:
            broadcastports = options.broadcastports

        if options.traffic_mode != None:
            set_traffic_mode(options.traffic_mode)

        info('I am %s aka %s\n' %(myself.get('nick'), myself.get('uid')))

    def cleanup(self):
        save_user()
        save_communities()
        self.save_plugin_state(None)

    def config_read(self):
        global myself

        uid = None

        linkpath = '%s/myself' % proximatedir
        try:
            linkvalue = os.readlink(linkpath)
        except OSError:
            linkvalue = None

        if self.options.identity != None:
            # Look for an uid
            ident = self.options.identity
            myself = get_user(ident)
            if myself == None:
                myself = create_user(ident)
        else:
            if linkvalue != None:
                # first see if the old 'myself' symlink is good
                uid = parse_user_dentry(linkvalue)
            if uid != None:
                myself = get_user(uid)

        if myself == None:
            create_myself()

        userdir = 'u_%s' % myself.get('uid')
        if userdir != linkvalue:
            xremove(linkpath)
            try:
                os.symlink(userdir, linkpath)
            except OSError, (errno, strerror):
                die('Can not create a symlink: %s -> %s (%s)\n' % (userdir, linkpath, strerror))

        myself.join_community(get_ordinary_community(DEFAULT_COMMUNITY_NAME), False)

    def get_plugin_state_path(self, pluginname):
        dname = get_user_dir(myself)
        basename = 'plugin_state_%s' %(pluginname)
        return os.path.join(dname, basename)

    def get_plugin_state(self, pluginname):
        pstate = self.pluginstorage.get(pluginname)
        if pstate == None:
            pstate = Plugin_State()
            fname = self.get_plugin_state_path(pluginname)
            try:
                f = open(fname, 'r')
            except IOError:
                f = None
            if f != None:
                pstatedata = f.read()
                f.close()
                pstate.read_python_file(pstatedata)
            self.pluginstorage[pluginname] = pstate
        return pstate

    def get_plugin_variable(self, pluginname, varname):
        return deepcopy(self.get_plugin_state(pluginname).get(varname))

    def save_plugin_state(self, pluginname):
        if pluginname == None:
            pluginitems = self.pluginstorage.items()
        else:
            pluginitems = [(pluginname, self.get_plugin_state(pluginname))]

        for (name, pstate) in pluginitems:
            if pstate.dirty:
                pstate.save_to_python_file(self.get_plugin_state_path(name))

    def set_plugin_variable(self, pluginname, varname, value):
        self.get_plugin_state(pluginname).set(varname, deepcopy(value))

def init(options):
    State_Plugin(options)
