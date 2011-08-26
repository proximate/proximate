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
from support import warning
from proximateprotocol import RPC_CLOSE, RPC_RELEASE

plugins_by_name = {}
rpc_commands = {}
rpc_pp_class = {}

registerorder = []

def register_rpchandler(cmd, rpchandler):
    """ register_rpchandler(cmd, rpchandler):

    An RPC handler is registered. The RPC handler is used to
    receive messages from network. Specifically, if an incoming
    TCP connection begins with a line containing 'cmd' string,
    rpchandler is called by rpchandler(data, eof, socket,
    address), where 'data' is the data received so far in the
    socket, 'eof' indicates whether there is more data still
    coming (if 'eof' == False, data can be partial).  'socket' is
    the TCP socket for remote, and 'address' is the network
    address of the remote end (ip address string, remote port).

    rpchandler() can be called many times until eof is True or more data
    comes. This allows incremental processing of incoming message
    (e.g. terminate invalid messages early).

    rpchandler() returns a value that is one of:

    RPC_MORE_DATA: the handler will want more data
    RPC_CLOSE:     the handler asks main handler to terminate the connection
    RPC_RELEASE:   the handler will take care of the socket from now on
    """

    if rpc_commands.has_key(cmd):
        warning('Can not install RPC handler: %s already exists\n' % cmd)
        return False
    rpc_commands[cmd] = rpchandler
    return True

class Plugin:
    def cleanup(self):
        """ At exit, each plugin's cleanup() method is called. This can be
        used for saving persistent data, kill running processes, close
        network connections, etc... """
        pass

    def community_changes(self, community):
        """ This is called after a community profile or icon is changed
        or acquired """
        pass

    def ready(self):
        """ Called after every plugin has been initialized. Note, GUI is
        not available yet. Use init_gui() method if you want to get called
        when ready() has been called for all plugins. """
        pass

    def register_server(self, ppclassname, ppclass):
        """ Register a server for RPC command name 'ppclassname'.
            'ppclass' is an object that refers to a server class
            that is instantiated on an incoming connection. 'ppclass'
            __init__ must be compatible following instantiation:

            ppclass(address=address, sock=sock, data=data)

            'address' is the incoming address tuple: (ip, port).
            'sock' is the socket that should be handled appropriately.
            The socket must be closed or used. 'data' is initial data
            that the server should handle. """

        global rpc_pp_class

        def accept(cmd, data, eof, sock, address):
            """ This is called by the rpc.py's tcp listener when a remote
            client connects """

            ppclass = rpc_pp_class.get(cmd)
            if ppclass == None:
                warning('No PP class found: %s\n' %(cmd))
                return RPC_CLOSE

            # Instantiate the given server class
            ppclass(address=address, sock=sock, data=data)
            return RPC_RELEASE

        if register_rpchandler(ppclassname, accept):
            rpc_pp_class[ppclassname] = ppclass

    def register_plugin(self, name):
        """ register_plugin() must be called before calling other methods
        from the Plugin base class """

        global plugins_by_name, registerorder

        if plugins_by_name.has_key(name):
            warning('Can not add a plugin with duplicate name\n')
            return False
        plugins_by_name[name] = self
        self.name = name
        registerorder.append(self)
        return True

    def user_appears(self, user):
        """ This is called when user appears """
        pass

    def user_changes(self, user, what=None):
        """ This is called when user's state changes.

        Optional 'what' parameter is a tuple (key, value). key must be an
        integer defined in proximateprotocols.py. The 'value' can have any type.

        Note, this is NOT called when user appears. """
        pass

    def user_disappears(self, user):
        """ Called when user disappears from community plugin's perspective """
        pass

def get_plugin_by_type(name):
    """ Return a plugin matching the given name """

    return plugins_by_name.get(name)

def get_plugins():
    return plugins_by_name.values()

def plugin_cleanup():
    l = list(registerorder)
    l.reverse()
    for plugin in l:
        plugin.cleanup()

def plugins_ready():
    """ Call ready() methods in registration order. This means
    state and community plugins must have values 0 and 1, respectively. """

    for plugin in registerorder:
        plugin.ready()
