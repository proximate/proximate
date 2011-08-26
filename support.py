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
import sys
import traceback

debug_mode = False
verbose_mode = False
version = 'none'
log_file = None

def debug(msg):
    global debug_mode
    if debug_mode:
        sys.stdout.flush()
        sys.stderr.write('%s' %(msg))
        sys.stderr.flush()
        write_log(msg)

def get_debug_mode():
    return debug_mode

def get_version():
    return version

def normal_mode():
    global debug_mode
    debug_mode = False

def set_debug_mode(verbose):
    global debug_mode
    global verbose_mode
    debug_mode = True
    verbose_mode = verbose
    if debug_mode:
        sys.stdout.write('Debug mode enabled\n')

def set_version(pversion):
    global version
    version = pversion

def die(msg, printstack=False):
    sys.stdout.flush()
    print_spot()
    sys.stderr.write('Error: %s' %(msg))
    sys.stderr.flush()
    write_log('die: ' + msg)
    if printstack:
        assert(False)
    else:
        sys.exit(1)

def warning(msg, printstack=False):
    sys.stdout.flush()
    print_spot()
    sys.stderr.write('Proximate warning: %s' %(msg))
    sys.stderr.flush()
    write_log('warning: ' + msg)
    if printstack:
        traceback.print_stack()

def print_exc():
    traceback.print_exc()
    if log_file:
        traceback.print_exc(file=log_file)

def info(msg):
    sys.stdout.flush()
    sys.stderr.write('Proximate: %s' %(msg))
    sys.stderr.flush()
    write_log(msg)

def print_spot(n=2):
    if verbose_mode:
        tb = traceback.extract_stack()[-n:][0]
        sys.stderr.write("From %s:%i\n" %(tb[0], tb[1]))

def set_log_file(path):
    global log_file
    try:
        log_file = open(path, 'w')
    except IOError:
        warning("Could not open log file %s\n" %(path))

def write_log(msg):
    if log_file:
        log_file.write(msg)

