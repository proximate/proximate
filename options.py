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
from optparse import OptionParser
import os
import sys

from support import die, get_version
from proximateprotocol import DEFAULT_PROXIMATE_PORT, valid_port

def get_options():
    parser = OptionParser()
    parser.add_option('-b', '--broadcast-port',
                      action = 'append',
                      type = 'int',
                      dest = 'broadcastports',
                      metavar = 'port',
                      help = 'Set UDP discovery ports. This option can be used multiple times to set multiple ports. You should always broadcast to the default port (%d) at least.' %(DEFAULT_PROXIMATE_PORT))
    parser.add_option('--chat-no-context',
                      default = True,
                      action = 'store_false',
                      dest = 'chatcontext',
                      help = 'Disable conversation context recovery and sending in chat. This option makes messaging unreliable.')
    parser.add_option('-d', '--debug',
                      default = False,
                      action = 'store_true',
                      dest = 'debug',
                      help = 'Debug mode')
    parser.add_option('--enable-key-exchange',
                      default = False,
                      action = 'store_true',
                      dest = 'key_exchange',
                      help = 'Enable key exchange. This is an experimental feature still in development. Default: disabled')
    parser.add_option('--enable-personal',
                      default = False,
                      action = 'store_true',
                      dest = 'personal_communities',
                      help = 'Enable personal communities. This is an experimental feature still in development. Default: disabled')
    parser.add_option('--enable-presence',
                      default = False,
                      action = 'store_true',
                      dest = 'presence',
                      help = 'Enable presence notification. This is an experimental feature still in development. Default: disabled')
    parser.add_option('-i', '--identity',
                      default = None,
                      dest = 'identity',
                      metavar = 'uid',
                      help = 'Assume identity x, where x is an uid')
    parser.add_option('-I', '--interface',
                      default = None,
                      dest = 'interface',
                      help = 'Set the network interface used by Proximate')
    parser.add_option('-n', '--no-gui',
                      default = True,
                      action = 'store_false',
                      dest = 'usegui',
                      help = 'No GUI')
    parser.add_option('-p', '--port',
                      type = 'int',
                      dest = 'activeport',
                      metavar = 'x',
                      help = 'Set UDP and TCP port to x. Default UDP port is %d. TCP port is randomized by default.' %(DEFAULT_PROXIMATE_PORT))
    parser.add_option('-t', '--proximate-dir',
                      default = None,
                      dest = 'proximatedir',
                      metavar = 'dir',
                      help = 'Set Proximate directory. Default: $HOME/.proximate')
    parser.add_option('--test',
                      default = None,
                      dest = 'test',
                      metavar = 'plugin',
                      help = 'Run self-test for plugin')
    parser.add_option('--traffic-mode',
                      default = None,
                      dest = 'traffic_mode',
                      metavar = 'x',
                      type = 'int',
                      help = 'Set traffic mode: 0 for normal traffic. 1 for minimal traffic. Normal traffic is the default.')
    parser.add_option('--udp-fetcher',
                      default = False,
                      action = 'store_true',
                      dest = 'udp_fetcher',
                      help = 'Use UDP for communication')
    parser.add_option('-u', '--udp-mode',
                      default = 3,
                      type = 'int',
                      dest = 'udpmode',
                      metavar = 'mask',
                      help = 'Set UDP mode to mask. 0 means no UDP traffic. 1 means listen but do not send broadcasts. 2 means send but do not listen to broadcasts. 3 (default) means both listen and send.')
    parser.add_option('-v', '--verbose',
                      default = False,
                      action = 'store_true',
                      dest = 'verbose',
                      help = 'Verbose debug output')
    parser.add_option('--version',
                      default = False,
                      action = 'store_true',
                      help = 'Print version number')
    (options, args) = parser.parse_args()

    if options.version:
        sys.stdout.write('Proximate %s\n' % get_version())
        sys.exit(0)

    display = os.getenv('DISPLAY')
    if display == None or len(display) == 0:
        options.usegui = False

    portlist = []
    if options.activeport != None:
        portlist.append(options.activeport)
    if options.broadcastports != None:
        portlist += options.broadcastports
    for port in portlist:
        if not valid_port(port):
            die('Invalid port given: %d\n' %(port))

    return (options, args)
