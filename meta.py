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
from pprint import pformat

from ossupport import safe_write
from support import warning
from proximateconfigparser import safe_write_config, \
     new_config, new_config_from_string, get_option
from utils import str_to_int

def is_unsigned_int(name, i):
    success = (type(i) in [int,long] and i >= 0)
    if not success:
        warning('profile: %s is not an unsigned integer: %s\n' %(name, str(i)))
    return success

def is_string_list(name, l):
    success = (type(l) == list)
    if not success:
        warning('profile: non-list parameter passed as %s\n' %(name))
        return False
    for s in l:
        if not type(s) == str:
            warning('profile: non-string element in %s\n' %(name))
            return False
    return True

def validate_list(l, f):
    if type(l) != list:
        return False
    for item in l:
        if not f(item):
            return False
    return True

class Meta_Attribute:
    def __init__(self, vtype, public=False, save=True, is_valid=None, default=None):
        self.public = public
        self.save = save
        self.vtype = vtype
        self.is_valid = is_valid
        self.default = default
        self.required = False
        self.save_processing = None

    def is_required(self):
        self.required = True

    def process_before_save(self, f):
        """ This filter is called from python_file(). It is used to alter
            data before saving it to a file. """

        self.save_processing = f

def publicbool(default=None):
    return Meta_Attribute(bool, public=True)

def privatebool(default=None):
    return Meta_Attribute(bool, public=False)

def publicstring(default=None):
    return Meta_Attribute(str, public=True)

def privatestring(default=None):
    return Meta_Attribute(str, public=False)

def publicunsignedint(default=None):
    return Meta_Attribute(int, public=True, is_valid=is_unsigned_int)

def privateunsignedint(default=None):
    return Meta_Attribute(int, public=False, is_valid=is_unsigned_int)

def publicstringlist(default=None):
    return Meta_Attribute(list, public=True, is_valid=is_string_list)

def privatestringlist(default=None):
    return Meta_Attribute(list, public=False, is_valid=is_string_list)

class Meta:
    def base_init(self):
        self.d = {}

        # Version number of this instance. This is a counter that is
        # incremented by one each time profile is visibly changed.
        self.metaattributes['v'] = Meta_Attribute(int, public=True, is_valid=is_unsigned_int, default=0)
        self.d['v'] = 0

        # Initialize public and private attributes
        self.reset_defaults(True)

        self.dirty = False
        self.fingerprintversion = -1

    def add_list_item(self, attr, value, validator=None):
        ma = self.metaattributes.get(attr)
        assert(ma != None)
        assert(ma.vtype == list)
        l = self.d.get(attr)
        if l == None:
            l = []
            self.d[attr] = l
        if (validator != None and validator(value) == False) or value in l:
            return False
        l.append(value)
        if ma.public:
            self.new_version()
        self.dirty = True
        return True

    def export_dictionary(self, trusted=False):
        d = {}
        for attr, val in self.d.items():
            ma = self.metaattributes.get(attr)
            if ma == None:
                if trusted == False:
                    continue
            else:
                if ma.save == False or (ma.public == False and trusted == False):
                    continue
            if val != None:
                d[attr] = val
        return d

    def get(self, attr):
        return self.d.get(attr)

    def new_version(self):
        self.d['v'] += 1

    def python_file(self):
        d = {}
        for attr, val in self.export_dictionary(trusted=True).items():
            ma = self.metaattributes.get(attr)
            if ma != None and ma.save_processing != None:
                val = ma.save_processing(self, val)
            d[attr] = val
        return pformat(d) + '\n'

    def read_config_section(self, c):
        if c.has_section(self.metasection) == False:
            return False
        self.reset_defaults(trusted=False)

        version = self.d['v']

        for (name, ma) in self.metaattributes.items():
            if ma.required and get_option(self.metasection, name) == None:
                warning('Missing required config attribute: %s\n' % name)
                return False

        for (name, value) in c.items(self.metasection):
            ma = self.metaattributes.get(name)
            if ma == None:
                continue
            if ma.public == False:
                warning('Ignoring %s:%s in %s\n' %(name, value, self.metasection))
                continue

            if ma.vtype == str:
                pass
            elif ma.vtype == bool:
                value = value.upper()
                if value == '0' or value == 'NO' or value == 'FALSE':
                    value = False
                elif value == '1' or value == 'YES' or value == 'TRUE':
                    value = True
                else:
                    continue
            elif ma.vtype == int:
                value = str_to_int(value, None)
                if value == None:
                    continue
            else:
                warning('Unknown vtype for %s in %s (type %s)\n' %(name, self.metasection, str(ma.vtype)))
                continue

            if self.set(name, value):
                if name == 'v':
                    version = value

        self.d['v'] = version
        return True

    def import_dictionary(self, d, trusted=False):
        if type(d) != dict:
            return False

        for (attr, ma) in self.metaattributes.items():
            if ma.required and d.get(attr) == None:
                warning('Missing required attribute %s\n' % attr)
                return False

        self.reset_defaults(trusted)

        success = True
        for attr, value in d.items():
            value = deepcopy(value)
            ma = self.metaattributes.get(attr)
            if ma == None:
                if trusted == False:
                    success = False
                    continue
            else:
                if ma.public == False and trusted == False:
                    warning('import_dictionary: ignored %s (not trusted): %s\n' %(attr, str(value)))
                    success = False
                    continue
                if ma.vtype != type(value):
                    warning('import_dictionary: ignored %s (invalid type): %s\n' %(attr, str(value)))
                    success = False
                    continue
                if ma.is_valid != None and ma.is_valid(attr, value) == False:
                    warning('import_dictionary: ignored %s (not valid): %s\n' %(attr, str(value)))
                    success = False
                    continue
            self.d[attr] = value
        return success

    def read_ini_file(self, s):
        c = new_config_from_string(s)
        if c == None:
            return False
        return self.read_config_section(c)

    def read_python_file(self, s):
        # Note, content of s is trusted, and it comes from the local
        # filesystem
        d = None
        try:
            d = eval(s)
        except ValueError:
            pass
        except TypeError:
            pass
        except SyntaxError:
            pass
        if type(d) != dict:
            d = None
        if d == None:
            warning('Can not read python file: %s\n' %(s))
            return False
        return self.import_dictionary(d, trusted=True)

    def remove_list_item(self, attr, value):
        ma = self.metaattributes.get(attr)
        assert(ma != None)
        assert(ma.vtype == list)
        l = self.d.get(attr)
        if l == None:
            return False
        try:
            l.remove(value)
        except ValueError:
            return False
        if ma.public:
            self.new_version()
        self.dirty = True
        return True

    def reset_defaults(self, trusted=False):
        """ If trusted == False, initialize only public values. Otherwise
            initialize private values too. """

        for attr, ma in self.metaattributes.items():
            if ma.public == False and trusted == False:
                continue
            self.d[attr] = deepcopy(ma.default)

    def save_to_config_section(self, c):
        c.add_section(self.metasection)

        for (attr, value) in self.d.items():
            if value == None:
                continue
            ma = self.metaattributes.get(attr)
            if ma == None:
                warning('No meta attribute for %s, can not save %s\n' %(attr, value))
                continue
            if ma.save == False or ma.public == False:
                continue

            if ma.vtype == type(''):
                pass
            elif ma.vtype == bool or ma.vtype == int:
                value = str(value)
            else:
                warning('Unknown vtype %s in %s (type %s)\n' %(vtype, self.metasection, str(ma.vtype)))
                continue

            try:
                c.set(self.metasection, attr, value)
            except TypeError, s:
                warning('Invalid option: %s:%s in %s\n' %(attr, value, self.metasection))
                raise TypeError(s)
        return True

    def save_to_ini_file(self, fname):
        c = new_config()
        if self.save_to_config_section(c):
            if safe_write_config(fname, c):
                self.dirty = False

    def save_to_python_file(self, fname):
        if safe_write(fname, self.python_file()):
            self.dirty = False

    def search_criteria(self, criteria, anycriteria):
        """ Test if user satisfied given criteria based on user data.
        Returns True in two cases:

          * if any criteria is met and anycriteria == True
          * if all criteria is met and anycriteria == False

        Otherwise False is returned. If number of criteria is zero,
        False is returned.

        criteria is a sequence of (attribute, value) pairs to be
        matched against user data.

        For example: criteria = [('name', 'john')] tests if user's
        name is 'john'.

        Note, this is a heuristic search, not exact. """

        matches = 0
        for (attribute, value) in criteria:
            ma = self.metaattributes.get(attribute)
            if ma == None or ma.public == False:
                warning('Unauthorized search (%s)\n' %(attribute))
                return False
        for (attribute, value) in criteria:
            if len(value) == 0:
                continue
            # Note, if data is a list, it is stringified first (hack)
            uservalue = str(self.d.get(attribute)).upper()
            match = (uservalue.find(value.upper()) >= 0)
            matches = int(match)
            if not match and not anycriteria:
                return False
            if match and anycriteria:
                return True
        return matches > 0

    def search_keywords(self, keywords, anykeyword):
        """ All searchable attributes are concatenated into a string
        (in update_fingerprint), and the resulting string is searched by
        keywords.

        Note, this is a heuristic search, not exact. """

        if len(keywords) == 0:
            return False
        self.update_fingerprint()
        matches = 0
        for keyword in keywords:
            if len(keyword) == 0:
                continue
            # self.fingerprint is already in upper case letters
            match = (self.fingerprint.find(keyword.upper()) >= 0)
            matches += int(match)
            if not match and not anykeyword:
                return False
            if match and anykeyword:
                return True
        return matches > 0

    def serialize(self):
        return self.export_dictionary(trusted=False)

    def set(self, attr, value):
        ma = self.metaattributes.get(attr)
        if ma != None:
            if value != None:
                if ma.is_valid != None and not ma.is_valid(attr, value):
                    warning('Invalid value for attribute %s: %s\n' %(attr, str(value)))
                    return False
            elif ma.required:
                warning('Meta attribute %s may not be None\n' % attr)
                return False
        if value == self.d.get(attr):
            return True
        if ma != None and ma.public:
            self.new_version()
        self.d[attr] = value
        self.dirty = True
        return True

    def unserialize(self, d):
        return self.import_dictionary(d, trusted=False)

    def update_attributes(self, attributes, version=None):
        """ Update one or more user attributes. They are given as a list of
        pairs: user.update_attributes([('ip', ip), ('port', port), ...])

        If attributes is an empty list, the profile version is just
        incremented by one. This is a guaranteed feature that allows
        profile update notifications to others.

        DD NOT use this function unless you know what you are doing. You
        profile.set() instead.
        """

        oldversion = self.d['v']

        for (attr, value) in attributes:
            if attr == 'v':
                version = value
            self.set(attr, value)

        if version == None:
            version = oldversion + 1

        self.d['v'] = version
        self.dirty = True

    def update_fingerprint(self):
        # self.dirty may not be used here. It is only used with user profiles.
        if self.d['v'] == self.fingerprintversion:
            return
        searchattrs = []
        for attr in self.d.keys():
            ma = self.metaattributes.get(attr)
            if ma != None and ma.public:
                searchattrs.append(attr)
        values = map(lambda key: str(self.d.get(key)).upper(), searchattrs)
        self.fingerprint = '\n'.join(values)
        self.fingerprintversion = self.d['v']
