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
from gobject import io_add_watch, source_remove, IO_IN, IO_HUP
from errno import EAGAIN, EINTR, EEXIST
from os import abort, close, fdopen, fork, kill, mkdir, \
     pipe, read, rename, remove, waitpid, write
import shutil
from signal import SIGTERM
from subprocess import Popen, PIPE
import os.path

from support import warning

def safe_write(fname, data, safe=True):
    tmpname = fname
    if safe:
        tmpname = fname + '.tmp'

    try:
        f = open(tmpname, 'w')
    except IOError, (errno, strerror):
        warning('Can not write to file %s: %s\n' %(tmpname, strerror))
        return False

    try:
        f.write(data)
    except IOError, (errno, strerror):
        warning('Can not write to %s\n' %(fname))
        return False
    f.close()

    if not safe:
        return True

    try:
        rename(tmpname, fname)
    except OSError, (errno, strerror):
        xremove(tmpname)
        warning('Rename failed: %s -> %s: %s\n' %(tmpname, fname, strerror))
        return False
    return True

def mkdir_parents(path):
    if os.path.isdir(path):
        return True
    if not mkdir_parents(os.path.dirname(path)):
        return False
    return xmkdir(path)

def xclose(fd):
    """ xclose() is similar to close() but doesn't throw an OSError exception.

    Returns 0 on success and -1 on failure."""

    try:
        close(fd)
    except OSError:
        return -1
    return 0

def xfork():
    """ xfork() is similar to fork but doesn't throw an OSError exception.

    Returns -1 on error, otherwise it returns the same value as fork() does.
    """

    try:
        ret = fork()
    except OSError:
        ret = -1
    return ret

def xmkdir(dirname, mode = 0700):
    try:
        mkdir(dirname, mode)
    except OSError, (errno, strerror):
        if errno != EEXIST:
            warning('Can not create a directory: %s\n' %(dirname))
            return False
    return True

def xpipe():
    """ xpipe() is similar to pipe() but doesn't throw an OSError exception.

    Returns read and write file descriptors for the new pipe, or (-1, -1)
    on OSError."""

    rfd = -1
    wfd = -1
    try:
        (rfd, wfd) = pipe()
    except OSError:
        pass
    return (rfd, wfd)

def xremove(pathname):
    try:
        remove(pathname)
    except OSError, (errno, strerror):
        return False
    return True

def xremovedir(dirname):
    try:
        shutil.rmtree(dirname)
    except OSError:
        return False
    return True

def xrename(src, dst):
    try:
        rename(src, dst)
    except OSError, (errno, strerror):
        return False
    return True

class xrunwatch:
    def __init__(self, fd, cb, ctx, childpid):
        self.fd = fd
        self.cb = cb
        self.ctx = ctx
        self.childpid = childpid
        self.realpid = None
        self.datalist = []
        self.tag = io_add_watch(fd, IO_IN | IO_HUP, self.watch)

    def cancel(self, sig=SIGTERM):
        if self.tag != None:
            if self.realpid == None:
                return False
            kill(self.childpid, sig)
            kill(self.realpid, sig)
            self.finish(None, False)
        return True

    def finish(self, output, call):
        xclose(self.fd)
        waitpid(self.childpid, 0)
        source_remove(self.tag)
        self.tag = None
        if call:
            self.cb(output, self.ctx)

    def watch(self, fd, condition):
        try:
            bytes = read(fd, 4096)
        except OSError, (errno, strerror):
            if errno == EAGAIN or errno == EINTR:
                return True
            warning('xrun: Surprising error code: %d %s\n' %(errno, strerror))
            self.finish(None, True)
            return False

        if self.realpid == None:
            try:
                ind = bytes.index('\0')
            except ValueError:
                warning('Very bad xrun() error\n')
                return False
            self.realpid = int(bytes[0:ind])
            bytes = bytes[ind + 1:]
            if len(bytes) > 0:
                self.datalist.append(bytes)
            return True

        if len(bytes) > 0:
            self.datalist.append(bytes)
            return True

        self.finish(''.join(self.datalist), True)
        return False

def xrun(cmd, cb, ctx, inputdata=None):
    """ Run 'cmd' (a list of command line arguments). Call cb(data, ctx),
    when the command finishes with its output given to cb() at parameter
    'data'. If 'inputdata' is given, feed it to the command from stdin.

    The result is relayed through the gobject mainloop.
    """

    (rfd, wfd) = xpipe()
    if rfd < 0:
        return False
    pid = xfork()
    if pid == -1:
        warning('Could not fork a new process\n')
        return False
    if pid != 0:
        xclose(wfd)
        return xrunwatch(rfd, cb, ctx, pid)

    xclose(rfd)

    w = fdopen(wfd, 'w')

    try:
        pipe = Popen(cmd, stdout=PIPE, stdin=PIPE)
    except OSError:
        warning('Unable to run %s\n' %(' '.join(cmd)))
        w.write('-1\0')
        abort()

    w.write(str(pipe.pid) + '\0')
    w.flush()

    if inputdata:
        try:
            pipein = pipe.stdin
            pipein.write(inputdata)
        except IOError:
            warning("IOError while writing to command %s\n" %(' '.join(cmd)))
            abort()
        pipein.close()

    try:
        pipeout = pipe.stdout
        result = pipeout.read()
    except IOError:
        warning("IOError while reading from command %s\n" %(' '.join(cmd)))
        abort()
    pipeout.close()

    pipe.wait()

    if pipe.returncode != 0:
        warning('%s did not exit cleanly\n' %(' '.join(cmd)))
        abort()

    w.write(result)
    w.close()
    abort()

def xsystem(cmd, inputdata=None):
    """ Run 'cmd' and return its output in a string. Optionally, 'inputdata'
    is written into command's stdin. """

    try:
        pipe = Popen(cmd, stdout=PIPE, stdin=PIPE)
    except OSError:
        warning('Unable to run %s\n' %(' '.join(cmd)))
        return None

    if inputdata:
        try:
            pipein = pipe.stdin
            pipein.write(inputdata)
        except IOError:
            warning("IOError while writing to command %s\n" %(' '.join(cmd)))
            return None
        finally:
            pipein.close()

    try:
        pipeout = pipe.stdout
        result = pipeout.read()
    except IOError:
        warning("IOError while reading from command %s\n" %(' '.join(cmd)))
        return None
    finally:
        pipeout.close()

    pipe.wait()
    if pipe.returncode != 0:
        warning('%s did not exit cleanly\n' %(' '.join(cmd)))
        return None
    return result
