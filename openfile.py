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

from support import warning
from subprocess import Popen, PIPE
from mimetypes import guess_type

def try_dbus(cmd, fullname):
    try:
        p = Popen(cmd, stdout = PIPE, stderr = PIPE)
    except OSError:
        warning('Opening %s failed\n' %(fullname))
        return False
    (stdout, stderr) = p.communicate()
    if len(stderr) != 0:
        warning('Opening %s failed\n' %(fullname))
        return False
    return True

def open_with_file_manager(path):
    d_bus_command = ['dbus-send', '--print-reply', '--dest=com.nokia.osso_filemanager', '/com/nokia/osso_filemanager', 'com.nokia.osso_filemanager.open_folder', 'string:file://%s' % path]
    return try_dbus(d_bus_command, path)

def open_file(fullname):
    if fullname == None:
        return False

    base, ext = os.path.splitext(fullname)

    fields = ['']
    (mimetype, encoding) = guess_type(fullname)
    if mimetype != None:
        fields = mimetype.split('/')

    # FIX: Find a way to open file with default application for file's mimetype
    # (currently there is a way to do this in C code (hildon_mime_open_file(),
    # but not in python?)
    file_string = 'string:file://%s' %(fullname)
    d_bus_command = None
    if fields[0] in ['video', 'audio'] or ext.lower() == '.mp4':
        d_bus_command = ['dbus-send', '--print-reply', '--dest=com.nokia.mediaplayer', '/com/nokia/mediaplayer', 'com.nokia.mediaplayer.mime_open', file_string]
    elif fields[0] == 'image':
        d_bus_command = ['dbus-send', '--print-reply', '--dest=com.nokia.image_viewer', '/com/nokia/image_viewer', 'com.nokia.image_viewer.mime_open', file_string]
    elif fields[0] == 'application' and fields[1] == 'pdf':
        # different file_string format here or pdfviewer can not open the file
        file_string = 'string:file:%s' %(fullname)
        d_bus_command = ['dbus-send', '--print-reply', '--dest=com.nokia.osso_pdfviewer', '/com/nokia/osso_pdfviewer', 'com.nokia.osso_pdfviewer.mime_open', file_string]

    if d_bus_command != None and try_dbus(d_bus_command, fullname):
        return True

    if fullname == None:
        return False

    if fields[0] in ['video', 'audio']:
        if open_file_with_player(fullname):
            return True

    # If all else fails, try a browser
    return open_file_with_browser(fullname)

def open_url(url):
    if check_exe('browser'):
        exe = 'browser'
        args = '--url=%s' % url
    elif check_exe('x-www-browser'):
        exe = 'x-www-browser'
        args = url
    elif check_exe('firefox'):
        exe = ['firefox']
        args = url
    else:
        return False

    os.spawnlp(os.P_NOWAIT, exe, exe, args)

    return True

def check_exe(exe):
    paths = os.getenv('PATH')
    if paths == None:
        return False
    for path in paths.split(':'):
        if os.access(path + '/' + exe, os.X_OK):
            return True
    return False

def find_exe(l):
    for (exe, f) in l:
        if check_exe(exe):
            return (exe, f)
    return (None, None)

def direct_open(fullname):
    return [fullname]

def file_url_open(fullname):
    return ['--url=file://%s' %(fullname)]

def open_to(ptype, l, fullname):
    (exe, f) = find_exe(l)
    if exe == None:
        warning('Can not open a %s\n' %(ptype))
        return False
    warning('Open %s to %s %s\n' %(fullname, ptype, exe))
    args = f(fullname)
    os.spawnlp(os.P_NOWAIT, exe, exe, *args)
    return True

def open_file_with_player(fullname):
    plist = [('vlc', direct_open),
             ('mplayer', direct_open),
            ]
    return open_to('player', plist, fullname)

def open_file_with_browser(fullname):
    blist = [('browser', file_url_open),
             ('x-www-browser', direct_open),
             ('firefox', direct_open)
            ]
    return open_to('browser', blist, fullname)
