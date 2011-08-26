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
from copy import deepcopy
from gobject import timeout_add, source_remove, io_add_watch, IO_OUT, PRIORITY_LOW
import os
from random import randrange, shuffle
import tempfile
from errno import ENXIO, EINTR, EAGAIN

from bencode import fmt_bdecode, bencode
from ioutils import TCP_Queue, filesize, TCPQ_ERROR
from content import Content_Meta
from plugins import Plugin, get_plugin_by_type
from support import info, warning, debug
from typevalidator import ANY, ZERO_OR_MORE, ONE_OR_MORE, OPTIONAL_KEY, validate
from proximateprotocol import PLUGIN_TYPE_COMMUNITY, PLUGIN_TYPE_FETCHER, \
     PLUGIN_TYPE_FILE_SHARING, PLUGIN_TYPE_STATE, \
     PLUGIN_TYPE_FILE_TRANSFER, PLUGIN_TYPE_NOTIFICATION, \
     TP_GET_FILE, TP_CONNECT_TIMEOUT, valid_community, \
     FS_PURPOSE_SHARE, FS_GID_LIMIT, FS_REPLICATE_DEFAULT_TTL, \
     FS_REPLICATE_MAX_SIZE, FS_REPLICATE_MAX_TTL, FS_REPLICATE_STORE_MAX, \
     FS_MAX_SHARES_TO_CHECK, valid_fs_gid, SHARE_BOGUS, \
     SHARE_DIR, SHARE_FILE, TP_MAX_TRANSFER, PLUGIN_TYPE_SETTINGS
from proximatestate import normal_traffic_mode
from utils import stepsafexrange, str_to_int, strip_extra_slashes, \
    unique_elements, timet_to_datetime, str_to_timet, \
    time_expired, format_bytes
from ossupport import mkdir_parents, xclose, xremove
from openfile import open_file

FTYPE_DIRECTORY   = 0
FTYPE_FILE        = 1

FIFO_INTERVAL = 500

QUERY_PROGRESS_TIMEOUT = 10

community = None
fetcher = None
filesharing = None
filetransfer = None
notification = None
state = None

gids = {}

def generate_meta_gid(meta):
    for i in xrange(100):
        gid = randrange(FS_GID_LIMIT)
        if gid not in gids:
            meta.set('gid', gid)
            return
    else:
        warning('Bad sunspots today\n')

def register_meta_gid(meta):
    gid = meta.get('gid')
    if gid != None:
        gids[gid] = meta

def search_filelist(names, qany, filelist):
    """ Do a search based on the file list """

    # Convert name search parameters
    for i in xrange(len(names)):
        # 1. remove non-empty strings
        nonempty = filter(lambda s: len(s) > 0, names[i])
        # 2. convert to upper-case
        names[i] = map(lambda s: s.upper(), nonempty)

    results = {}
    for (sharename, info) in filelist.items():
        uppername = sharename.upper()
        any = False
        all = True
        for namelist in names:
            match = (len(namelist) > 0)
            for name in namelist:
                if uppername.find(name) < 0:
                    match = False
            if match:
                any = True
            else:
                all = False
        if qany:
            found = any
        else:
            found = all
        if found:
            results[sharename] = info

    return results

class Get_File:
    ackspec = {'flen': lambda flen: (type(flen) == int or type(flen) == long) and flen >= 0}

    def __init__(self, user, name, files, cb, ctx, silent, totallen):
        self.q = TCP_Queue(self.msghandler, closehandler=self.queue_closed)
        self.user = user
        self.f = None
        self.name = name
        self.pending = files
        self.nfiles = len(files)
        self.ui = None
        self.pos = None
        self.flen = None
        self.silent = silent
        self.cb = cb
        self.ctx = ctx
        self.totallen = totallen

    def queue_closed(self, q, parameter, msg):
        if self.f != None:
            self.f.close()
            self.f = None
        if self.ui != None:
            self.ui.cleanup('End')
            self.ui = None
        if self.cb != None:
            self.cb(len(self.pending) == 0, self.ctx)
            self.cb = None

        if len(self.pending) > 0:
            if self.nfiles > 1:
                msg = 'Unable to get a directory %s from %s:\nDirectory download not supported on the server side,\nor node is not reachable.' % (self.name, self.user.get('nick'))
                notification.ok_dialog('File download error', msg)
            else:
                msg = 'Unable to download file %s from %s' % (self.name, self.user.get('nick'))
                notification.notify(msg, not self.silent)
                        
        self.name = None

    def begin(self):
        filetransfer = get_plugin_by_type(PLUGIN_TYPE_FILE_TRANSFER)
        if filetransfer != None and self.totallen != None:
            title = 'Receiving from %s: %s' % (self.user.get('nick'), self.name)
            self.ui = filetransfer.add_transfer(title, self.totallen, self.abort_cb, silent=self.silent)

        return self.connect()

    def abort_cb(self, ctx):
        self.q.close(msg='Aborted')

    def connect(self):
        ip = self.user.get('ip')
        port = self.user.get('port')
        if ip == None or port == None or not self.q.connect((ip, port), TP_CONNECT_TIMEOUT):
            return False

        prefix = TP_GET_FILE + '\n'
        self.q.write(prefix, writelength = False)

        myuid = community.get_myuid()
        req = {'uid': myuid}
        self.q.write(bencode(req))

        for (shareid, sharepath, destname) in self.pending:
            req = {'id': shareid, 'path': sharepath, 'keepalive': 0}
            self.q.write(bencode(req))

        # Close queue that is idle for a period of time
        self.q.set_timeout(TP_CONNECT_TIMEOUT)

        return True

    def msghandler(self, q, data, parameter):
        d = fmt_bdecode(self.ackspec, data)
        if d == None:
            warning('get file: invalid msg: %s\n' % data)
            return False

        if len(self.pending) == 0:
            warning('get file: queue is empty!\n')
            return False

        self.pos = 0
        self.flen = d['flen']

        (shareid, sharepath, destname) = self.pending[0]

        mkdir_parents(os.path.dirname(destname))

        try:
            self.f = open(destname, 'w')
        except IOError, (errno, strerror):
            warning('Unable to write to a file %s: %s\n' %(destname, strerror))
            return False

        notification.notify('Receiving a file from %s: %s (%s)' % (self.user.get('nick'), self.name, format_bytes(self.flen)))

        filetransfer = get_plugin_by_type(PLUGIN_TYPE_FILE_TRANSFER)
        if filetransfer != None and self.ui == None:
            title = 'Receiving from %s: %s' % (self.user.get('nick'), self.name)
            self.ui = filetransfer.add_transfer(title, self.flen, self.abort_cb, silent=self.silent)

        self.q.set_recv_handler(self.receive)
        return True

    def receive(self, data):
        amount = min(len(data), self.flen - self.pos)

        try:
            self.f.write(data[0:amount])
        except IOError, (errno, strerror):
            self.q.close(TCPQ_ERROR, msg=strerror)
            return None

        self.pos += amount

        if self.ui != None:
            self.ui.update(amount)

        if self.flen == self.pos:
            self.f.close()
            self.f = None
            self.q.set_recv_handler(None)
            notification.notify('Received a file from %s succefully: %s' % (self.user.get('nick'), self.name))
            self.pending.pop(0)
            if len(self.pending) == 0:
                self.q.close(msg='Complete')
                return None

        return amount

class Get_File_Server:
    """ Process incoming file request connection """

    hellospec = {'uid': str}
    getspec = {'id': int, 'path': str}

    def __init__(self, address, sock, data):
        self.q = TCP_Queue(self.msghandler, closehandler=self.queue_closed)

        # Close queue that is idle for a period of time
        self.q.set_timeout(TP_CONNECT_TIMEOUT)

        self.address = address
        self.f = None
        self.ui = None
        self.pos = None
        self.user = None
        self.name = None
        self.flen = None
        self.keepalive = False

        self.q.append_input(data)
        self.q.initialize(sock)

    def queue_closed(self, q, parameter, msg):
        if self.f != None:
            self.f.close()
            self.f = None
        if self.ui != None:
            self.ui.cleanup('End')
            self.ui = None
        if self.name != None and self.pos < self.flen:
            notification.notify('Unable to send a file to %s: %s' % (self.user.get('nick'), self.name), True)

    def abort_cb(self, ctx):
        self.q.close(msg='Aborted')

    def msghandler(self, q, data, parameter):
        if self.user == None:
            spec = self.hellospec
        else:
            spec = self.getspec
        d = fmt_bdecode(spec, data)
        if d == None:
            warning('file server: invalid msg: %s\n' % data)
            return False
        if self.user == None:
            self.user = community.safe_get_user(d['uid'], self.address[0])
            if self.user == None:
                warning('file server: invalid uid: %s\n' % d['uid'])
                return False
            return True

        fname = filesharing.serve_fname(d['id'], d['path'])
        if fname == None:
            return False

        try:
            self.f = open(fname, 'r')
        except IOError, (errno, strerror):
            warning('Unable to open a file %s: %s\n' %(fname, strerror))
            return False

        try:
            self.f.seek(0, os.SEEK_END)
        except IOError, (errno, strerror):
            warning('Unable to seek file %s: %s\n' %(fname, strerror))
            return False

        self.keepalive = d.has_key('keepalive')

        self.pos = 0
        self.flen = self.f.tell()
        self.f.seek(0)

        self.name = os.path.basename(fname)

        notification.notify('Sharing a file to %s: %s (%s)' % (self.user.get('nick'), self.name, format_bytes(self.flen)))

        filetransfer = get_plugin_by_type(PLUGIN_TYPE_FILE_TRANSFER)
        if filetransfer != None:
            title = 'Sharing to %s: %s' % (self.user.get('nick'), self.name)
            self.ui = filetransfer.add_transfer(title, self.flen, self.abort_cb, silent=True)

        self.q.write(bencode({'flen': self.flen}))

        self.q.set_send_handler(self.send)
        self.q.throttle()
        return True

    def send(self):
        amount = min(TP_MAX_TRANSFER * 4, self.flen - self.pos)

        if not self.keepalive and amount == 0:
            # Close the connection, as the client does not support persistent
            # connections
            self.q.set_send_handler(None)
            self.q.close_after_send()
            return ''

        try:
            chunk = self.f.read(amount)
        except IOError, (errno, strerror):
            self.q.close(TCPQ_ERROR, msg=strerror)
            return None

        self.pos += amount

        if self.ui != None:
            self.ui.update(amount)

        if self.pos == self.flen:
            self.f.close()
            self.f = None
            if self.ui != None:
                self.ui.cleanup('End')
                self.ui = None
            notification.notify('Sent a file to %s succefully: %s' % (self.user.get('nick'), self.name))
            if self.keepalive:
                self.q.set_send_handler(None)
                self.q.throttle(False)

        return chunk

class Stream:
    ackspec = {'flen': lambda flen: (type(flen) == int or type(flen) == long) and flen >= 0}

    def __init__(self, user, shareid, sharepath):
        self.q = TCP_Queue(self.msghandler, closehandler=self.queue_closed)
        self.user = user
        self.fd = None
        self.shareid = shareid
        self.sharepath = sharepath
        self.name = os.path.basename(sharepath)
        self.ui = None
        self.pos = 0
        self.flen = None
        self.fifoname = None
        self.wtag = None
        self.fifochecktag = None
        self.initstate = True
        self.timeout = 30

    def queue_closed(self, q, parameter, msg):
        if self.fd != None:
            os.close(self.fd)
            self.fd = None
        if self.fifoname != None:
            xremove(self.fifoname)
        if self.fifochecktag != None:
            source_remove(self.fifochecktag)
            self.fifochecktag = None
        self.writewait(False)
        if self.ui != None:
            self.ui.cleanup('End')
            self.ui = None
        self.name = None

    def begin(self):
        return self.connect()

    def abort_cb(self, ctx):
        self.q.close(msg='Aborted')

    def connect(self):
        ip = self.user.get('ip')
        port = self.user.get('port')
        if ip == None or port == None or not self.q.connect((ip, port), TP_CONNECT_TIMEOUT):
            return False

        prefix = TP_GET_FILE + '\n'
        self.q.write(prefix, writelength = False)

        myuid = community.get_myuid()
        req = {'uid': myuid}
        self.q.write(bencode(req))

        req = {'id': self.shareid, 'path': self.sharepath}
        self.q.write(bencode(req))

        # Close queue that is idle for a period of time
        self.q.set_timeout(TP_CONNECT_TIMEOUT)

        return True

    def msghandler(self, q, data, parameter):
        self.initstate = False
        d = fmt_bdecode(self.ackspec, data)
        if d == None:
            warning('get file: invalid msg: %s\n' % data)
            return False

        self.flen = d['flen']

        (fd, self.fifoname) = tempfile.mkstemp(prefix='proximate-stream-', suffix=self.name)
        xclose(fd)
        xremove(self.fifoname)

        try:
            os.mkfifo(self.fifoname, 0600)
        except OSError, (errno, strerror):
            warning('can not create FIFO %s: %s\n' % (self.fifoname, strerror))
            return False

        open_file(self.fifoname)

        notification.notify('Streaming a share from %s: %s (%s)' % (self.user.get('nick'), self.name, format_bytes(self.flen)))

        filetransfer = get_plugin_by_type(PLUGIN_TYPE_FILE_TRANSFER)
        if filetransfer != None:
            title = 'Streaming from %s: %s' % (self.user.get('nick'), self.name)
            self.ui = filetransfer.add_transfer(title, self.flen, self.abort_cb, silent=True)

        self.fifochecktag = timeout_add(FIFO_INTERVAL, self.check_fifo)

        self.q.set_recv_handler(self.receive)
        self.q.throttle()
        return True

    def check_fifo(self):
        """ Check if the FIFO is opened by the player application """

        try:
            self.fd = os.open(self.fifoname, os.O_WRONLY|os.O_NONBLOCK)
        except OSError, (errno, strerror):
            if errno == ENXIO and self.timeout > 0:
                self.timeout -= 1
                return True
            notification.notify('Unable to stream to the player application', True)
            self.q.close(TCPQ_ERROR, msg=strerror)
            return False

        debug('FIFO ready!\n')
        self.writewait()

        return False

    def writewait(self, writeenable=True):
        if writeenable:
            if self.wtag == None:
                self.wtag = io_add_watch(self.fd, IO_OUT, self.fifo_write, priority=PRIORITY_LOW)
        elif self.wtag != None:
            source_remove(self.wtag)
            self.wtag = None

    def fifo_write(self, fd, cond):
        """ The FIFO can be now written to. Full speed ahead! """

        self.q.throttle(False)
        self.writewait(False)
        return False

    def receive(self, data):
        amount = min(len(data), self.flen - self.pos)

        try:
            written = os.write(self.fd, data[0:amount])
        except OSError, (errno, strerror):
            if errno != EAGAIN and errno != EINTR:
                self.q.close(TCPQ_ERROR, msg=strerror)
                return None
            written = 0

        self.pos += written

        if self.ui != None:
            self.ui.update(written)

        if written < amount:
            self.q.throttle()
            self.writewait()

        if self.flen == self.pos:
            self.q.close(msg='Complete')
            return None

        return written

class Share:
    def __init__(self, path, sharemeta, save):
        self.valid = True
        self.save = save
        self.meta = sharemeta

        self.filemetas = {}
        self.sharename = None

        self.path = strip_extra_slashes(path)

        if self.meta.get('type') == SHARE_BOGUS:
            return
        elif self.meta.get('type') == SHARE_DIR:
            if not os.path.isdir(path):
                warning('filesharing: path %s is not a directory\n' %(path))
                self.valid = False
                return
            self.dname = path
            self.fname = None
        elif self.meta.get('type') == SHARE_FILE:
            if not os.path.isfile(path):
                warning('filesharing: path %s is not a file\n' %(path))
                self.valid = False
                return
            self.dname = os.path.dirname(path)
            self.fname = os.path.basename(path)

        if len(path) == 0 or path[0] != '/':
            warning('filesharing: you must use an absolute path for initializing a share\n')
            self.valid = False
            return

        self.read_filemetas()

    def check_share_path(self, sharepath):
        if len(sharepath) == 0:
            return False
        if sharepath[0] != '/':
            warning('filesharing: share path must be an absolute path: %s\n' %(sharepath))
            return False
        # Reject paths with '..' subterfuge
        fields = sharepath.split('/')
        return not ('..' in fields)

    def deinit(self):
        self.valid = False

    def serve_fname(self, sharepath):
        if self.meta.get('type') == SHARE_FILE and sharepath == '/':
            sharepath = '/' + self.fname

        fname = self.native_path(sharepath)
        if fname == None:
            warning('filesharing: invalid path for GET: %s\n' %(sharepath))
            return None

        if self.meta.get('type') == SHARE_FILE and fname != self.path:
            warning('filesharing: GET file does not match a share path: %s != %s\n' %(fname, self.path))
            return None
        return fname

    def get_filemeta(self, sharename=None, forceread=False):
        if sharename == None:
            sharename = self.sharename
        meta = self.filemetas.get(sharename)
        if meta == None or forceread:
            meta = self.read_one_meta(sharename)
        return meta

    def get_filemeta_string(self, sharename):
        meta = self.get_filemeta(sharename)
        if meta == None:
            return None
        return meta.serialize()

    def get_id(self):
        return self.meta.get('id')

    def list_dir(self, path):
        try:
            # . and .. are filtered out
            l = os.listdir(path)
        except OSError, (errno, strerror):
            l = None
        return l

    def list_path(self, sharepath = '/'):
        if self.meta.get('type') == SHARE_BOGUS:
            return None
        elif self.meta.get('type') == SHARE_FILE:
            if sharepath != '/':
                return None
            return {'/' + self.fname: FTYPE_FILE}

        assert(self.meta.get('type') == SHARE_DIR)

        path = self.native_path(sharepath)
        if path == None:
            warning('filesharing: invalid path: %s\n' %(sharepath))
            return None

        flist = self.list_dir(path)
        if flist == None:
            warning('filesharing: invalid or unlistable path: %s\n' %(path))
            return None
        entries = {}
        for name in flist:
            fullpath = os.path.join(sharepath, name)
            nativepath = self.native_path(fullpath)
            if os.path.isdir(nativepath):
                entries[fullpath] = FTYPE_DIRECTORY
            else:
                entries[fullpath] = FTYPE_FILE
        return entries

    def list_recursively(self, sharepath = '/'):
        """ Use DFS (Depth First Seach) to list files recursively """

        entries = {}

        q = [sharepath]
        processed = {}
        while len(q) > 0:
            sharepath = q.pop()
            if processed.has_key(sharepath):
                continue
            processed[sharepath] = None

            pathlist = self.list_path(sharepath)
            if pathlist == None:
                continue

            for (path, ftype) in pathlist.items():
                if ftype == FTYPE_DIRECTORY:
                    q.append(path)
                entries[path] = ftype
        return entries

    def native_path(self, sharepath):
        # sharepath is the name of the file inside the file share. It is
        # an absolute path with respect to the share's root.

        if not self.check_share_path(sharepath):
            return None

        # Skip leading / characters, to get a path relative to the share root
        i = 0
        while i < len(sharepath):
            if sharepath[i] != '/':
                break
            i += 1
        relpath = sharepath[i:]
        if len(relpath) == 0:
            return self.dname

        # Return a native absolute path
        return os.path.join(self.dname, relpath)

    def query_by_criteria(self, criteria, qany, filelist):
        names = []
        foundother = False
        for (attribute, value) in criteria:
            if attribute == 'fname':
                names.append(value.split())
            else:
                foundother = True

        results = {}
        if len(names) > 0 and (qany or foundother == False):
            results = search_filelist(names, qany, filelist)

        for (sharepath, info) in filelist.items():
            meta = self.filemetas.get(sharepath)
            if meta != None:
                if meta.search_criteria(criteria, qany):
                    results[sharepath] = info

        return results

    def query_by_keywords(self, keywords, qany, filelist):
        names = map(lambda s: [s], keywords)

        results = search_filelist(names, qany, filelist)

        for (sharepath, info) in filelist.items():
            meta = self.filemetas.get(sharepath)
            if meta != None:
                if meta.search_keywords(keywords, qany):
                    results[sharepath] = info

        return results

    def read_one_meta(self, sharename):
        path = self.native_path(sharename)
        if path == None or path[-1] == '/':
            return None
        meta = Content_Meta()
        if not meta.read_meta(path):
            return None
        self.filemetas[sharename] = meta
        return meta

    def read_filemetas(self):
        self.filemetas = {}

        if self.meta.get('type') == SHARE_BOGUS:
            return
        elif self.meta.get('type') == SHARE_FILE:
            self.sharename = '/' + self.fname
            self.read_one_meta(self.sharename)
            return

        # It's a directory
        assert(self.meta.get('type') == SHARE_DIR)

        self.sharename = '/'
        ndentries = 0
        files = []

        for (relpath, ftype) in self.list_recursively().items():
            if ftype == FTYPE_FILE:
                ndentries += 1
            if ndentries == 50:
                warning('Refreshing file share %s: THIS MAY TAKE A LONG TIME. BUG ALERT: Network timeout possible.\n' %(self.path))
            self.read_one_meta(relpath)

        self.meta.set('nfiles', ndentries)

    def serialize(self):
        return self.meta.serialize()

    def serialize_to_disk(self):
        if not self.valid or not self.save:
            return None
        return {'path': self.path,
                'sharemeta': self.meta.serialize_to_disk(),
               }

    def update_meta(self, sharepath, meta):
        if sharepath == None:
            sharepath = self.sharename
        self.filemetas[sharepath] = meta
        path = self.native_path(sharepath)
        if not os.path.exists(path):
            warning('update_meta(): %s does not exist\n' % path)
            return
        meta.save_meta(path)

class Share_Meta:
    """ 'gid' is a message identifier that is unique in probabilistic sense.
        It can be collided by anyone. 'gid' should be a 64-bit (random)
        unsigned integer less than FS_GID_LIMIT. Python does not limit the
        effective range of integers, but other implementations may benefit
        from the constraint. The message creator may choose it freely,
        so other implementations can actually use a range much smaller
        than 64-bits. The downside is the increased chance for gid collision.
    """

    validator = {str: ANY,
                 'id': lambda i: type(i) == int and i >= 0,
                 'purpose': lambda s: type(s) == str and len(s) > 0,
                 'description': str,
                 'type': lambda s: s in [SHARE_BOGUS, SHARE_DIR, SHARE_FILE],
                 OPTIONAL_KEY('community'): lambda s: valid_community(s),
                 OPTIONAL_KEY('dst'): str,
                 OPTIONAL_KEY('gid'): valid_fs_gid,
                 OPTIONAL_KEY('src'): str,
                 OPTIONAL_KEY('timestart'): int,  # time_t
                 OPTIONAL_KEY('timeend'): int,    # time_t
                 OPTIONAL_KEY('ttl'): lambda i: type(i) == int and i >= 0,
                }

    def __init__(self, d=None):
        """ Dictionary items in d are imported into the Share_Meta instance
        iff d != None. Note, values are not (deep)copied, only references
        are passed. The resulting Share_Meta is not validated. """

        # 'shared' attribute is False iff the meta is not published to others.
        # Usually this happens when one gets a Share_Meta from another peer.
        # 'mine' attribute is False iff the published item was not created
        # by myself.
        self.priv = {'mine': True,
                     'shared': False,
                    }
        self.d = {'description': ''}
        if d != None:
            for (key, value) in d.items():
                self.d[key] = value

    def __str__(self):
        return 'Share_Meta ' + str(self.d)

    def __getitem__(self, name):
        return self.d[name]

    def __setitem__(self, name, value):
        self.set(name, value)

    def decrement_ttl(self):
        ttl = min(FS_REPLICATE_MAX_TTL, self.get('ttl') - 1)
        self.set('ttl', ttl)

    def expire_at(self, timeend):
        return self.set_time('timeend', timeend)

    def get(self, name):
        return self.d.get(name)

    def get_priv(self, name):
        return self.priv.get(name)

    def replicate(self, ttl=FS_REPLICATE_DEFAULT_TTL, withidentity=False):
        assert(ttl >= 0)
        self.set('ttl', ttl)
        if withidentity:
            self.set('src', community.get_myuid())
        if ttl > 0 and self.get('gid') == None:
            generate_meta_gid(self)
        self.set_priv('mine', True)

    def serialize(self):
        return deepcopy(self.d)

    def serialize_to_disk(self):
        return (self.serialize(), deepcopy(self.priv))

    def set(self, name, value):
        self.d[name] = value

    def set_priv(self, name, value):
        self.priv[name] = value

    def set_time(self, name, s):
        # Convert timestamp string to time_t integer
        t = str_to_timet(s)
        if t == None:
            return False
        self.set(name, int(t))
        return True

    def start_at(self, timestart):
        return self.set_time('timestart', timestart)

    def test_expiration(self):
        timeend = self.get('timeend')
        if timeend == None:
            return False
        dt = timet_to_datetime(timeend)
        return dt == None or time_expired(dt)

    def test_replication(self, sizetest=False):
        if self.get('purpose') == FS_PURPOSE_SHARE:
            return False
        gid = self.get('gid')
        if gid == None or gids.has_key(gid):
            return False
        ttl = self.get('ttl')
        if ttl == None or ttl <= 1:
            return False
        if len(bencode(self.d)) > FS_REPLICATE_MAX_SIZE:
            warning('Too large a chunk to be replicated: %s\n' % str(self.d))
            return False
        return not self.test_expiration()

    def unserialize(self, metadict):
        if not self.validate(metadict):
            warning('Invalid metadict: %s\n' % str(metadict))
            self.d = {}
            return False
        self.d = deepcopy(metadict)
        self.set_priv('mine', False)
        return True

    def unserialize_from_disk(self, metainfo):
        if type(metainfo) != tuple or len(metainfo) != 2:
            warning('Invalid metainfo in database: %s\n' % str(metainfo))
            return False
        if not self.unserialize(metainfo[0]):
            return False
        self.priv = deepcopy(metainfo[1])
        return self.priv.get('mine') == True

    def validate(self, d=None):
        if d == None:
            d = self.d
        return validate(self.validator, d)

class Subscription:
    def __init__(self, purpose, callback):
        self.purpose = purpose
        self.callback = callback

    def __str__(self):
        return 'purpose %s' % self.purpose

    def query(self, user, sharemeta):
        if sharemeta['purpose'] != self.purpose:
            return
        shareid = sharemeta['id']
        if not filesharing.remember_test(user, shareid, ''):
            filesharing.remember(user, shareid, '')
            self.callback(user, sharemeta)

class File_Sharing_Plugin(Plugin):
    """ Do not change these numbers. They are network protocol numbers. """
    CMD_ANNOUNCE_SHARES  = 'announce'
    CMD_GET_METAS        = 'get_metas'
    CMD_LIST_SHARES      = 'list_shares'
    CMD_QUERY            = 'query'

    listsharesspec = {OPTIONAL_KEY('ids'): [ZERO_OR_MORE, int],
                      OPTIONAL_KEY('purpose'): str,
                     }

    def __init__(self):
        self.register_plugin(PLUGIN_TYPE_FILE_SHARING)
        self.register_server(TP_GET_FILE, Get_File_Server)

        # my shares
        self.shares = {}

        self.subs = []

        self.sharestocheck = []
        self.sharechecktag = None

        self.usersnextshareid = {}

        self.downloads = {}

        # XXX: TO DO: Number of simultaneous file shares access policy

        self.fetchhandlers = {
            self.CMD_ANNOUNCE_SHARES: self.slave_announce_shares,
            self.CMD_GET_METAS: self.slave_get_metas,
            self.CMD_LIST_SHARES: self.slave_list_shares,
            self.CMD_QUERY: self.slave_query,
            }

    def add_share(self, path='', purpose=FS_PURPOSE_SHARE, sharemeta=None, announce=True, save=True, stype=SHARE_BOGUS):
        """ Note: The new share is saved on cleanup iff save == True.
            Path can be None. """

        # Find next free share id
        myself = community.get_myself()
        shareid = myself.get('fscounter')
        while self.shares.has_key(shareid):
            shareid += 1

        if sharemeta == None:
            sharemeta = Share_Meta()
        sharemeta['id'] = shareid
        sharemeta['purpose'] = purpose
        sharemeta['type'] = stype

        if not sharemeta.validate():
            warning('add_share(): Invalid Share_Meta %s\n' % str(sharemeta))
            return None

        share = self.create_share(path, sharemeta, save)
        if share == None:
            return None

        myself.set('fscounter', shareid + 1)
        if save:
            self.save_shares()
        if announce and normal_traffic_mode():
            self.announce_shares([shareid])
        return share

    def create_share(self, path, sharemeta, save):
        shareid = sharemeta['id']
        assert(shareid not in self.shares)
        share = Share(path, sharemeta, save)
        if not share.valid:
            return None
        self.shares[shareid] = share
        register_meta_gid(sharemeta)
        sharemeta.set_priv('shared', True)
        return share

    def gen_share_list(self, shareids, purpose=None):
        metas = []
        for shareid in shareids:
            share = self.get_share(shareid, purpose=purpose)
            if share != None:
                metas.append(share.serialize())
        return {'uid': community.get_myuid(),
                'metas': metas,
               }

    def announce_shares(self, shareids, com=None):

        request = self.gen_share_list(shareids)
        request['t'] = self.CMD_ANNOUNCE_SHARES

        if com == None:
            com = community.get_default_community()

        fetcher.fetch_community(com, PLUGIN_TYPE_FILE_SHARING, request, None, ack=False)

    def check_shares_helper(self, shares):
        republish = []
        for (user, meta) in shares:
            for sub in self.subs:
                sub.query(user, meta)

            if not meta.test_replication(sizetest=True):
                continue
            meta.decrement_ttl()
            share = self.add_share(None, purpose=meta['purpose'], sharemeta=meta, announce=False)
            if share != None:
                republish.append(share.meta.get('id'))

        if len(republish) == 0:
            return

        if normal_traffic_mode():
            self.announce_shares(republish)

        self.check_share_redistribution()

    def check_share_redistribution(self):
        warning('Checking share redistribution (NOT OPTIMIZED)\n')
        if len(self.shares) < FS_REPLICATE_STORE_MAX:
            return
        shares = []
        for shareid in self.shares.keys():
            share = self.get_share(shareid)
            if share == None:
                continue
            meta = share.meta
            if meta.get_priv('mine'):
                continue
            if meta.test_replication():
                shares.append((shareid, share))
            else:
                self.remove_share(share)

        # Remove lowest share id (oldest) first
        shares.sort()
        shares.reverse()

        while len(shares) > FS_REPLICATE_STORE_MAX:
            (shareid, share) = shares.pop()
            self.remove_share(share)
            warning('Not redistributing share anymore: %s\n' % str(share.meta))

    def check_share_after_timeout(self, user, meta):
        """ This is called from timeout set in slave_announce_shares() """

        def timeout_handler():
            shares = unique_elements(self.sharestocheck)
            shuffle(shares)
            self.check_shares_helper(shares)
            self.sharestocheck = []
            self.sharechecktag = None
            return False

        self.sharestocheck.append((user, meta))
        if self.sharechecktag == None:
            self.sharechecktag = timeout_add(500, timeout_handler)

    def check_user_shares(self, user, oldshareid, nextshareid):

        def check_user_shares_handler(user, metas, ctx):
            if metas != None:
                for meta in metas:
                    self.check_share_after_timeout(user, meta)

        d = nextshareid - oldshareid
        if d < 0:
            oldshareid = 0
        # Check N latest shares
        oldshareid = max(oldshareid, nextshareid - FS_MAX_SHARES_TO_CHECK)
        shareids = list(xrange(oldshareid, nextshareid))
        self.list_user_shares(user, check_user_shares_handler, None, shareids=shareids)

    def process_share_list(self, request):
        validator = {'uid': str,
                     'metas': [ZERO_OR_MORE, {}],
                    }
        if not validate(validator, request):
            return None

        metas = []
        for metadict in request['metas']:
            sharemeta = Share_Meta()
            if sharemeta.unserialize(metadict):
                metas.append(sharemeta)
            else:
                warning('Slave got an invalid share meta: %s\n' % (str(metas[i])))
        return metas

    def cleanup(self):
        self.save_shares()
        self.save_downloads()

    def fix_share_path(self, sharepath):
        sharepath = strip_extra_slashes(sharepath)
        if len(sharepath) == 0:
            warning('fix_share_path: empty path\n')
            return sharepath
        if sharepath[0] != '/':
            # canonize filenames, allow "foo" even if "/foo" is the proper name
            newpath = '/' + sharepath
            sharepath = newpath
        return sharepath

    def get_files(self, user, name, files, callback, ctx=None, silent=False, totallen=None):
        """ Passing sharepath == '/' gets a single file and its meta data.
            This is only allowed if the share is a single file share.

            callback(success, ctx) """

        def save_meta(metas, destdict):
            if len(metas) != 1:
                return
            (shareid, sharepath, meta) = metas[0]
            meta.save_meta(destdict[(shareid, sharepath)])

        metalist = []
        destdict = {}
        for (shareid, sharepath, destname) in files:
            metalist.append((shareid, sharepath))
            destdict[(shareid, sharepath)] = destname
        self.get_metas(user, metalist, save_meta, destdict)

        get = Get_File(user, name, files, callback, ctx, silent, totallen)
        return get.begin()

    def stream(self, user, shareid, sharepath):
        s = Stream(user, shareid, sharepath)
        return s.begin()

    def get_download_path(self, pathname=None):
        d = self.download_path_setting.value
        if pathname == None:
            return d

        basename = os.path.basename(pathname)
        fname = os.path.join(d, basename)
        base, ext = os.path.splitext(basename)
        counter = 1
        while os.path.exists(fname):
            fname = os.path.join(d, '%s-%d%s' % (base, counter, ext))
            counter += 1
        return fname

    def get_metas(self, user, files, callback, ctx):
        """ Get metas related to files.
        Metas are passed to the caller with a callback.

        files is a sequence of (shareid, sharepath) pairs. """

        request = {'t': self.CMD_GET_METAS,
                   'shareids': [],
                   'sharepaths': [],
                  }
        for (shareid, sharepath) in files:
            request['shareids'].append(shareid)
            request['sharepaths'].append(self.fix_share_path(sharepath))
        return fetcher.fetch(user, PLUGIN_TYPE_FILE_SHARING, request, self.parse_metas, (callback, ctx))

    def get_share(self, shareid, purpose=None):
        share = self.shares.get(shareid)
        if share != None and purpose != None and purpose != share.meta['purpose']:
            return None
        return share

    def get_shares(self, purpose=None):
        shares = []
        for share in self.shares.values():
            if purpose == None or purpose == share.meta['purpose']:
                shares.append(share)
        return shares

    def get_users_next_shareid(self, user):
        if user == None:
            return 0
        nextshareid = user.get('fscounter')
        if nextshareid == None:
            nextshareid = 0
        return nextshareid

    def list_community_shares(self, com, callback, ctx, purpose=None):
        if callback == None:
            return False
        d = {'t': self.CMD_LIST_SHARES}
        if purpose != None:
            d['purpose'] = purpose
        fetcher.fetch_community(com, PLUGIN_TYPE_FILE_SHARING, d, self.parse_user_shares, (callback, ctx))

    def list_user_shares(self, user, callback, ctx, shareids=None, purpose=None):
        """ Get share metas from a user """

        if callback == None:
            return False
        d = {'t': self.CMD_LIST_SHARES}
        if shareids != None:
            d['ids'] = shareids
        if purpose != None:
            d['purpose'] = purpose
        return fetcher.fetch(user, PLUGIN_TYPE_FILE_SHARING, d, self.parse_user_shares, (callback, ctx), retries=1)

    def native_path(self, shareid, sharepath):
        share = self.get_share(shareid)
        if share == None:
            return None
        return share.native_path(sharepath)

    def parse_metas(self, user, reply, tup):
        # Master side handler to parse file/directory metas (not share metas)

        (callback, ctx) = tup
        metas = []
        if reply == None:
            callback(metas, ctx)
            return

        validator = {
            'shareids': [ZERO_OR_MORE, lambda x: type(x) == int and x >= 0],
            'sharepaths': [ZERO_OR_MORE, str],
            'metas': [ZERO_OR_MORE, {}],
            }
        if not validate(validator, reply):
            warning('Invalid get_metas reply: %s\n' %(str(reply)))
            callback(metas, ctx)
            return

        for (shareid, sharepath, contentmeta) in zip(reply['shareids'], reply['sharepaths'], reply['metas']):
            meta = Content_Meta()
            if meta.import_meta(contentmeta):
                metas.append((shareid, sharepath, meta))
            else:
                warning('Got invalid metastring: %s\n' %(metacfg))
        callback(metas, ctx)

    def parse_query_results(self, user, reply, tup):
        # Master side handler: called by fetcher

        (callback, ctx) = tup
        if reply == None:
            callback(user, None, {}, ctx)
            return

        validator = {
            'rfields': lambda l: l == ['shareid', 'name', 'size', 'type'],
            'shareid': [ZERO_OR_MORE, lambda x: type(x) == int and x >= 0],
            'name': [ZERO_OR_MORE, str],
            'size': [ZERO_OR_MORE, lambda x: type(x) == int and x >= 0],
            'type': [ZERO_OR_MORE, lambda x: type(x) == int and x >= 0],
            'metas': {int: {}},
            }
        if not validate(validator, reply):
            warning('Invalid query reply: %s\n' %(str(reply)))
            callback(user, None, {}, ctx)
            return

        metadict = reply['metas']
        for shareid in metadict.keys():
            meta = Share_Meta()
            if not meta.unserialize(metadict[shareid]):
                warning('Invalid metas in query reply: %s\n' % str(reply))
                callback(user, None, {}, ctx)
                return
            metadict[shareid] = meta

        for shareid in reply['shareid']:
            if shareid not in metadict:
                warning('Missing meta in query reply: %d -> ?\n' % shareid)
                callback(user, None, {}, ctx)
                return

        callback(user, zip(reply['shareid'], reply['name'], reply['size'], reply['type']), metadict, ctx)

    def parse_query_community_results(self, user, reply, ctx):
        if reply == None:
            # ignore timeouts
            return False
        self.parse_query_results(user, reply, ctx)

    def parse_user_shares(self, user, reply, tup):
        # Master side handler: called by fetcher

        (callback, ctx) = tup
        metas = self.process_share_list(reply)
        # Note, metas is allowed to be None (which indicates a bad message)
        callback(user, metas, ctx)

    def progress_update(self, msg):
        self.indicator.set_status(msg)

    def query(self, user, callback, ctx=None, criteria=None, keywords=None, any=True, shareid=-1, sharepath='/'):
        """ If shareid == -1, all shares are queries. Otherwise only the given
            shareid will be queried. """

        request = {'t': self.CMD_QUERY,
                   'path': sharepath,
                   'shareid': shareid,
                   'rfields': ['shareid', 'name', 'size', 'type'],
                   'any': any,
                  }
        if criteria != None:
            request['criteria'] = {}
            for (attribute, value) in criteria:
                request['criteria'][attribute] = value
        elif keywords != None:
            request['keywords'] = list(keywords)

        return fetcher.fetch(user, PLUGIN_TYPE_FILE_SHARING, request, self.parse_query_results, (callback, ctx))

    def query_community(self, com, callback, ctx=None, criteria=None, keywords=None, any=True):
        request = {'t': self.CMD_QUERY,
                   'path': '/',
                   'shareid': -1,
                   'rfields': ['shareid', 'name', 'size', 'type'],
                   'any': any,
                  }
        if criteria != None:
            request['criteria'] = {}
            for (attribute, value) in criteria:
                request['criteria'][attribute] = value
        elif keywords != None:
            request['keywords'] = list(keywords)

        self.indicator.set_status('Querying shares', timeout=QUERY_PROGRESS_TIMEOUT)
        return fetcher.fetch_community(com, PLUGIN_TYPE_FILE_SHARING, request, self.parse_query_community_results, (callback, ctx))

    def ready(self):
        global community, fetcher, filesharing, filetransfer, notification, state
        community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        fetcher = get_plugin_by_type(PLUGIN_TYPE_FETCHER)
        filesharing = self
        filetransfer = get_plugin_by_type(PLUGIN_TYPE_FILE_TRANSFER)
        notification = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION)
        state = get_plugin_by_type(PLUGIN_TYPE_STATE)

        self.indicator = notification.get_progress_indicator('File sharing')

        fetcher.register_handler(PLUGIN_TYPE_FILE_SHARING, self.slave_handler, 'filesharing')

        settings = get_plugin_by_type(PLUGIN_TYPE_SETTINGS)
        self.download_path_setting = settings.register('filesharing.download_path', str, 'Download path', default=None, validator=self.validate_path)

        if self.download_path_setting.value == None:
            for path in ['~/MyDocs/.documents', '~/Downloads', '~/Documents', '/tmp']:
                if self.download_path_setting.set(os.path.expanduser(path)):
                    break

        self.read_shares()
        self.read_downloads()

    def read_downloads(self):
        self.downloadsname = os.path.join(community.get_user_dir(), 'downloads')
        try:
            f = open(self.downloadsname, 'r')
        except IOError, (errno, strerror):
            return
        s = f.read()
        f.close()
        fields = s.split('\0')
        for i in stepsafexrange(0, len(fields), 3):
            uid = fields[i]
            user = community.get_user(uid)
            if user == None:
                continue
            shareid = str_to_int(fields[i + 1], -1)
            if shareid < 0:
                warning('Invalid shareid: %s\n' %(fields[i + 1]))
                continue
            sharepath = fields[i + 2]
            self.remember(user, shareid, sharepath, save=False)

    def read_shares(self):
        """ Shares are defined in PROXIMATEDIR/u_MYSELF/filesharing.

        Each share is just a section name that depicts the file or directory.
        RFC 822 format is used. """

        shares = state.get_plugin_variable(self.name, 'shares')
        if shares == None:
            return
        if not validate({int: {'path': str, 'sharemeta': ANY}}, shares):
            warning('Invalid share in database: %s\n' %(str(shares)))
            return

        for (shareid, d) in shares.items():
            sharemeta = Share_Meta()
            if not sharemeta.unserialize_from_disk(d.get('sharemeta')):
                warning('Can not read share meta in database: %s\n' % str(d))
                continue
            path = strip_extra_slashes(d['path'])
            s = self.create_share(path, sharemeta, True)
            if s == None:
                warning('Could not add share %s\n' % path)

    def remember_code(self, uid, shareid, sharepath):
        return '%s\0%d\0%s\0' %(uid, shareid, sharepath)

    def remember(self, user, shareid, sharepath, save=True):
        """ This function is used to remember downloads from other users.
        It will affect subscription downloads so that already downloaded
        files will not be downloaded again by the subscription model. """

        uid = user.get('uid')
        if self.downloads.has_key(uid) == False:
            self.downloads[uid] = {}
        usershares = self.downloads[uid]
        if usershares.has_key(shareid) == False:
            usershares[shareid] = {}
        usershares[shareid][sharepath] = None

        if not save:
            return

        try:
            f = open(self.downloadsname, 'a')
        except IOError, (errno, strerror):
            warning('Can not append to %s\n' %(self.downloadsname))
            return
        f.write(self.remember_code(uid, shareid, sharepath))
        f.close()

    def remember_test(self, user, shareid, sharepath):
        uid = user.get('uid')
        usershares = self.downloads.get(uid)
        if usershares == None:
            return False
        sharefiles = usershares.get(shareid)
        if sharefiles == None:
            return False
        return sharefiles.has_key(sharepath)

    def remove_share(self, share):
        if self.shares.pop(share.get_id(), None) != None:
            share.deinit()
            self.save_shares()
        else:
            warning('Share %d already removed\n' % share.get_id())

    def remove_subscription(self, purpose):
        """ Remove all subscribtions whose purpose matches the given one """

        self.subs = filter(lambda s: s.purpose != purpose, self.subs)

    def save_downloads(self):
        try:
            f = open(self.downloadsname, 'w')
        except IOError:
            warning('Can not save downloads to %s\n' %(self.downloadsname))
            return
        for (uid, usershares) in self.downloads.items():
            for shareid in usershares.keys():
                for sharepath in usershares[shareid].keys():
                    f.write(self.remember_code(uid, shareid, sharepath))
        f.close()

    def save_shares(self):
        d = {}
        for share in self.get_shares():
            s = share.serialize_to_disk()
            if s != None:
                d[share.get_id()] = s
        state.set_plugin_variable(self.name, 'shares', d)
        state.save_plugin_state(self.name)

    def set_download_path(self, path):
        return self.download_path_setting.set(path)

    def slave_announce_shares(self, from_user, request):
        """ slave side: register shares announced by the user. Note, uid can be
        faked. Not that this matters.. Announcements are only used for making
        a delay shorter. This also means indirect announcements are possible.
        """

        if not normal_traffic_mode():
            return {}

        metas = self.process_share_list(request)
        if metas == None:
            warning('Invalid announce shares: %s\n' %(str(request)))
            return {}
        user = community.get_user(request['uid'])
        if user != from_user:
            warning('Invalid uid in announcement: %s\n' % str(request))
            return {}
        # Test each new share for interesting data, after a period of time
        for meta in metas:
            self.check_share_after_timeout(user, meta)
        return {}

    def slave_get_metas(self, user, request):
        """ slave side handler for file/directory meta requests """

        validator = {
            'shareids': [ZERO_OR_MORE, lambda x: type(x) == int and x >= 0],
            'sharepaths': [ZERO_OR_MORE, str],
            }
        if not validate(validator, request):
            warning('Invalid slave_get_metas request: %s\n' %(str(request)))
            return None

        reply = {'shareids': [], 'sharepaths': [], 'metas': []}
        for (shareid, sharepath) in zip(request['shareids'], request['sharepaths']):
            share = self.get_share(shareid)
            if share == None:
                continue

            qname = sharepath
            if qname == '/':
                qname = None
            metastring = share.get_filemeta_string(qname)
            if metastring == None:
                continue

            reply['shareids'].append(shareid)
            reply['sharepaths'].append(sharepath)
            reply['metas'].append(metastring)

        return reply

    def serve_fname(self, shareid, sharepath):
        share = self.get_share(shareid)
        if share == None:
            return None
        return share.serve_fname(sharepath)

    def slave_handler(self, user, request):
        # Slave side handler: called by fetcher
        handler = self.fetchhandlers.get(request['t'])
        if handler == None:
            warning('Filesharing not handling request: %s\n' %(str(request)))
            return None
        return handler(user, request)

    def slave_list_shares(self, user, request):
        if not validate(self.listsharesspec, request):
            warning('Invalid list shares request: %s\n' % str(request))
            return None

        shareids = request.get('ids')
        if shareids == None:
            shareids = self.shares.keys()
        purpose = request.get('purpose')
        return self.gen_share_list(shareids, purpose=purpose)

    def slave_query(self, user, request):
        validator = {'shareid': int,
                     'rfields': [ONE_OR_MORE, str],
                     OPTIONAL_KEY('path'): str,
                    }
        if not validate(validator, request):
            warning('Invalid query: %s\n' %(str(request)))
            return fetcher.SILENT_COMMUNITY_ERROR
        request.setdefault('path', '/')
        request.setdefault('recursive', 1)

        reply = {}
        for rname in request['rfields']:
            if rname not in ['name', 'size', 'type', 'meta', 'shareid']:
                warning('Invalid rfield requested in query: %s\n' %(rname))
                return fetcher.SILENT_COMMUNITY_ERROR
            if reply.get(rname) != None:
                warning('Duplicate rfield in list query: %s\n' %(rname))
                return fetcher.SILENT_COMMUNITY_ERROR
            reply[rname] = []
        reply['rfields'] = list(request['rfields'])

        shareid = request['shareid']
        if shareid == -1:
            shares = self.get_shares()
        else:
            share = self.get_share(shareid)
            if share == None:
                return fetcher.SILENT_COMMUNITY_ERROR
            shares = [share]

        qany = request.get('any', True)
        criteria = request.get('criteria')
        keywords = request.get('keywords')
        if criteria != None:
            if not validate({str: str}, criteria):
                warning('Invalid criteria\n')
                return fetcher.SILENT_COMMUNITY_ERROR
        elif keywords != None:
            if not validate([ONE_OR_MORE, str], keywords):
                warning('Invalid keywords\n')
                return fetcher.SILENT_COMMUNITY_ERROR

        sharepath = request['path']
        metadict = {}

        for share in shares:
            if request['recursive'] != 0:
                filelist = share.list_recursively(sharepath)
            else:
                filelist = share.list_path(sharepath)
            if filelist == None:
                return fetcher.SILENT_COMMUNITY_ERROR

            # Filter results
            if criteria != None:
                items = criteria.items()
                filelist = share.query_by_criteria(items, qany, filelist)
            elif keywords != None:
                filelist = share.query_by_keywords(keywords, qany, filelist)

            if filelist == {}:
                continue

            metadict[share.meta.get('id')] = share.meta.serialize()

            # Generate result listing
            for (sharename, ftype) in filelist.items():
                for rname in request['rfields']:
                    if rname == 'name':
                        reply[rname].append(sharename)
                    elif rname == 'size':
                        size = 0
                        if ftype == FTYPE_FILE:
                            nativepath = share.native_path(sharename)
                            size = filesize(nativepath)
                        reply[rname].append(size)
                    elif rname == 'type':
                        reply[rname].append(ftype)
                    elif rname == 'meta':
                        reply[rname].append('')
                    elif rname == 'shareid':
                        reply[rname].append(share.get_id())

        if len(metadict) == 0 and len(request['c']) > 0:
            # Do not answer for a community fetch that yields empty result
            return fetcher.POSTPONE_REPLY

        reply['metas'] = metadict

        return reply

    def subscribe(self, newsub):
        """ Subscribe to FS events: new files, announcements, etc """

        self.subs.append(newsub)

    def user_appears(self, user):
        # Record next share id for detecting new unseen shares
        self.usersnextshareid[user] = self.get_users_next_shareid(user)

    def user_changes(self, user, what=None):
        """ This is called when a new user appears into the network """
        if community.is_me(user):
            return

        oldshareid = self.usersnextshareid.get(user, 0)
        nextshareid = self.get_users_next_shareid(user)
        if oldshareid != nextshareid:
            notification.user_notify(user, 'has published content')
            if normal_traffic_mode():
                self.check_user_shares(user, oldshareid, nextshareid)

        # Record next share id for detecting new unseen shares
        self.usersnextshareid[user] = nextshareid

    def validate_path(self, path):
        if len(path) == 0 or path[0] != '/':
            return False
        return os.path.isdir(path)

def init(options):
    File_Sharing_Plugin()
