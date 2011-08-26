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
from ConfigParser import SafeConfigParser, NoOptionError, NoSectionError, MissingSectionHeaderError
import os
from StringIO import StringIO

from ossupport import xremove
from support import warning
from utils import str_to_int

def get_boolean_option(c, section, option, default=None):
    value = get_option(c, section, option)
    if value == None:
        return default
    up = value.upper()
    if up == '0' or up == 'NO' or up == 'FALSE':
        return False
    if up == '1' or up == 'YES' or up == 'TRUE':
        return True
    return default

def get_option(c, section, option, options=None, default=None):
    value = None
    try:
        value = c.get(section, option)
    except NoOptionError:
        pass
    except NoSectionError:
        pass
    if value == None or (options != None and value not in options):
        value = default
    return value

def get_integer_option(c, section, option, default=None):
    value = get_option(c, section, option)
    if value == None:
        return default
    return str_to_int(value, default)

def new_config():
    return SafeConfigParser()

def new_config_from_string(s):
    c = new_config()
    try:
        c.readfp(StringIO(s))
    except MissingSectionHeaderError:
        pass
    if len(c.sections()) == 0:
        warning('Bad config string. Invalid number of sections: %d\n' %(len(c.sections())))
        return None
    return c

def safe_write_config(cfgname, c, safe=True):
    tmpname = cfgname
    if safe:
        tmpname = cfgname + '.tmp'

    try:
        f = open(tmpname, 'w')
    except IOError, (errno, strerror):
        warning('Can not write to file %s: %s\n' %(tmpname, strerror))
        return False

    c.write(f)
    f.close()

    if not safe:
        return True

    try:
        os.rename(tmpname, cfgname)
    except OSError, (errno, strerror):
        xremove(tmpname)
        warning('Rename failed: %s -> %s: %s\n' %(tmpname, cfgname, strerror))
        return False
    return True

def serialize_config(c):
    f = StringIO()
    c.write(f)
    s = f.getvalue()
    f.close()
    return s

def set_boolean_option(c, section, name, value, alternatives=('no', 'yes')):
    s = alternatives[int(bool(value))]
    c.set(section, name, s)

def set_option(c, section, name, value):
    c.set(section, name, value)
