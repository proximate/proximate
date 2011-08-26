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
from plugins import Plugin, get_plugin_by_type
from proximateprotocol import PLUGIN_TYPE_SETTINGS
from utils import str_to_int
from proximatestate import get_config_name
from proximateconfigparser import new_config, safe_write_config, get_option

CONFIG_SECTION = 'settings'

class Setting:
    def __init__(self, name, vtype, descr, value, validator):
        self.name = name
        self.vtype = vtype
        self.descr = descr
        self.value = value
        self.validator = validator
        self.dirty = False

    def set(self, value):
        if value != None and type(value) != self.vtype:
            return False
        if self.validator != None:
            if not self.validator(value):
                return False
        self.value = value
        self.dirty = True
        return True

class Settings_Plugin(Plugin):
    def __init__(self, options):
        self.register_plugin(PLUGIN_TYPE_SETTINGS)

        self.settings = []
        self.new_setting_cb = []

    def register(self, name, vtype, descr, default=None, validator=None):
        cfgname = get_config_name()
        c = new_config()
        value = None
        if len(c.read(cfgname)) != 0:
            value = get_option(c, CONFIG_SECTION, name, None, None)
        if vtype == str:
            pass
        elif vtype == bool:
            if value != None:
                value = value.upper()
            if value == '0' or value == 'NO' or value == 'FALSE':
                value = False
            elif value == '1' or value == 'YES' or value == 'TRUE':
                value = True
            else:
                value = None
        elif vtype == int:
            if value != None:
                value = str_to_int(value, None)

        if value == None:
            value = default

        s = Setting(name, vtype, descr, value, validator)
        self.settings.append(s)

        for cb in self.new_setting_cb:
            cb(s)
        return s

    def write_settings(self):
        cfgname = get_config_name()
        c = new_config()
        c.add_section(CONFIG_SECTION)
        for s in self.settings:
            c.set(CONFIG_SECTION, s.name, str(s.value))
            s.dirty = False
        safe_write_config(cfgname, c)

    def cleanup(self):
        self.write_settings()

def init(options):
    Settings_Plugin(options)
