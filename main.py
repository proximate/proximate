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
import random
import sys

from plugins import plugin_cleanup, plugins_ready
import support
import proximatestate
import listener
from support import die, print_exc, warning

def main(options, args):
    if options.debug:
        support.set_debug_mode(options.verbose)

    # Initialize seed for crypto and other plugins
    random.seed()

    # Init order for plugins: proximatestate, wlancontrol, community, ... (others)
    # State plugin must be the second plugin that is initialized
    proximatestate.init(options)

    # 'wlancontrol' and 'community' must be initialized first in this order
    for modulename in ['wlancontrol', 'community', 'udpfetcher',
                       'sendfile', 'tcpfetcher', 'fetcher',
                       'filesharing', 'settings',
                       'keymanagement', 'notify',
                       'messaging', 'scheduler', 'messageboard',
                       'userpresence', 'vibra']:
        module = __import__(modulename)
        try:
            module.init(options)
        except TypeError:
            raise
            die('module %s init() called with invalid arguments\n' %(modulename))

    proximatestate.load_external_plugins(options=options)

    plugins_ready()

    listener.init()

    rval = 1
    try:
        if options.usegui:
            from guihandler import run_gui
            run_gui()
        else:
            from cursesui import run_ui
            run_ui()
        rval = 0
    except Exception, err:
        import traceback
        print_exc()
        warning("proximate exception: %s\n" % err)
    finally:
        plugin_cleanup()

    if rval == 0:
        msg = 'success'
    else:
        msg = 'failure'
    sys.stdout.write('Proximate terminates (%s)\n' %(msg))
    sys.exit(rval)
