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
Try to determine local IP and broadcast IP, report when IP changes
"""
import dbus
from dbus.mainloop.glib import DBusGMainLoop
from dbus.exceptions import DBusException

from plugins import Plugin, get_plugin_by_type
from support import debug, info
from utils import str_to_int
from ioutils import get_ip_address
from proximateprotocol import PLUGIN_TYPE_NETWORK_CONTROL, PLUGIN_TYPE_SCHEDULER

POLL_INTERVAL = 5

ICD_INTERFACE = 'Nokia ICd'

def ip_number(ip):
    fields = ip.split('.')
    if len(fields) != 4:
        return None
    ipnumber = 0
    for f in fields:
        ipnumber <<= 8
        val = str_to_int(f, -1)
        if val < 0 or val > 255:
            return None
        ipnumber += val
    return ipnumber

def ip_string(ipnumber):
    fields = []
    shift = 24
    while shift >= 0:
        fields.append(str((ipnumber >> shift) & 0xff))
        shift -= 8
    return '.'.join(fields)

class Network_Control(Plugin):
    def __init__(self, options):
        self.system_bus = None
        self.local_ip = None
        self.broadcast_addr = None
        self.interfaces = {}
        self.use_interface = options.interface

        self.register_plugin(PLUGIN_TYPE_NETWORK_CONTROL)

    def ready(self):
        if self.use_interface == None:
            if self.initialize_icd():
                info('Using Nokia ICd\n')
                return

        devlist = []
        if self.use_interface != None:
            # user specified inteface
            devlist.append(self.use_interface)
        else:
            devlist.append('bat0')
            for i in xrange(3):
                devlist.append('wlan%d' %(i))
            for i in xrange(9):
                devlist.append('eth%d' %(i))

        for dev in devlist:
            (ip, bcast) = self.get_ip_address(dev)
            if ip != None:
                info('Using interface %s: %s %s\n' % (dev, ip, bcast))
            self.interfaces[dev] = (ip, bcast)

        sch = get_plugin_by_type(PLUGIN_TYPE_SCHEDULER)
        sch.call_periodic(POLL_INTERVAL * sch.SECOND, self.periodic_poll)

    def initialize_icd(self):
        DBusGMainLoop(set_as_default=True)

        self.system_bus = dbus.SystemBus()
        self.system_bus.add_signal_receiver(self.status_changed_handler, 'status_changed',
                                            'com.nokia.icd', 'com.nokia.icd',
                                            '/com/nokia/icd')

        try:
            self.icd = self.system_bus.get_object('com.nokia.icd', '/com/nokia/icd',
                                                  introspect=False)
        except DBusException:
            return False

        try:
            self.icd.get_state(dbus_interface='com.nokia.icd')
        except DBusException:
            return False

        self.interfaces[ICD_INTERFACE] = (None, None)
        return True

    def status_changed_handler(self, iap, bearer, state, *args):
        """ Handles connection events received from Internet
            Connectivity daemon. """

        if state == 'CONNECTED':
            debug('ICd: connected\n')
            self.interfaces[ICD_INTERFACE] = (None, None)
            try:
                self.icd.get_ipinfo(dbus_interface='com.nokia.icd',
                                    reply_handler=self.icd_reply,
                                    error_handler=self.icd_error)
            except DBusException:
                pass

        elif state == 'DISCONNECTING':
            debug('ICd: disconnecting\n')
            self.interfaces[ICD_INTERFACE] = (None, None)

    def icd_error(self, excp):
        pass

    def icd_reply(self, *args):
        ip = str(args[1])
        ipnumber = ip_number(ip)
        netmasknumber = ip_number(args[2])

        invmask = ((1 << 32) - 1) ^ netmasknumber

        # Assume broadcast address is the highest number address in the subnet
        bcast = ip_string(ipnumber | invmask)

        debug('ICd: IP reply: %s %s\n' % (ip, bcast))
        self.interfaces[ICD_INTERFACE] = (ip, bcast)

    def periodic_poll(self, t, ctx):
        for (dev, state) in self.interfaces.items():
            (ip, bcast) = self.get_ip_address(dev)
            if (ip, bcast) != state:
                debug('IP changed for %s: %s %s\n' % (dev, ip, bcast))
                self.interfaces[dev] = (ip, bcast)
        return True

    def get_ip_address(self, dev):
        not_available = (None, None)

        if not self.test_if_up(dev):
            return not_available

        (ip, bcast) = get_ip_address(dev)
        if ip == '':     # No address assigned
            return not_available

        return (ip, bcast)

    def test_if_up(self, dev):
        try:
            f = open('/sys/class/net/%s/operstate' %(dev), 'r')
        except IOError:
            # Maybe we don't have a sysfs. Assume the device exists -> return True
            return True
        isup = not f.read().startswith('down')
        f.close()
        return isup

    def get_interfaces(self):
        return self.interfaces

def init(options):
    Network_Control(options)
