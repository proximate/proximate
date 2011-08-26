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
import random
from hashlib import sha1
from base64 import b64encode
from gobject import timeout_add

from plugins import Plugin, get_plugin_by_type
from ossupport import xclose, xpipe, xremove, xsystem, xrun
from support import debug, warning
from typevalidator import validate
from proximateprotocol import PLUGIN_TYPE_FETCHER, PLUGIN_TYPE_KEY_MANAGEMENT, \
    PLUGIN_TYPE_COMMUNITY, PLUGIN_TYPE_NOTIFICATION, PLUGIN_TYPE_STATE, \
    valid_uid

from keymanagement_gui import Key_Management_GUI

class Key_Management_Plugin(Plugin):

    KM_REQUEST_KEY = 'keymanagement request key'
    KM_REQUEST_ACK = 'keymanagement request ack'
    KM_REQUEST_NACK = 'keymanagement request nack'
    KM_REQUEST_OK = 'keymanagement request ok'
    KM_REQUEST_DENIED = 'keymanagement request denied'
    KM_REQUEST_ANSWER_ACK = 'keymanagement request answer ack'
    KM_TEMP_KEY1 = 'keymanagement temp key a'
    KM_TEMP_KEY2 = 'keymanagement temp key b'
    KM_TEMP_KEY_ACK = 'keymanagement temp key ack'
    KM_PERM_KEY1 = 'keymanagement perm key a'
    KM_PERM_KEY2 = 'keymanagement perm key b'
    KM_PERM_KEY_ACK = 'keymanagement perm key ack'
    KM_FINISHED = 'keymanagement finished'
    KM_CANCEL = 'keymanagement cancel'
    KM_PROTOCOL_VIOLATION = 'keymanagement protocol violation'
    KM_ERROR = 'keymanagement error'

    def __init__(self):
        self.register_plugin(PLUGIN_TYPE_KEY_MANAGEMENT)
        self.temp_passphrase = ""

        self.sslname = 'openssl'
        self.symmetric = 'aes-128-cbc'
        self.passphraselen = 6

        self.current = {'user': None, 'state': None}
        self.temp_session_key = [None, None]

        self.temp_key_watcher = None

        self.key_exchange_gui = None

    def ready(self):
        self.fetcher = get_plugin_by_type(PLUGIN_TYPE_FETCHER)
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)
        self.indicator = get_plugin_by_type(PLUGIN_TYPE_NOTIFICATION).get_progress_indicator('Key management')
        proximatestate = get_plugin_by_type(PLUGIN_TYPE_STATE)
        if proximatestate.options.key_exchange:
            self.fetcher.register_handler(PLUGIN_TYPE_KEY_MANAGEMENT, self.handle_requests, 'key fetch')
        self.myself = self.community.get_myself()
        self.my_uid = self.myself.get('uid')

    def init_gui(self, main_gui):
        self.key_management_gui = Key_Management_GUI(main_gui)

        # wait for some time after initialization and
        # then check if permanent key has been created
        timeout = timeout_add(5000, self.check_perm_key)

    def register_ui(self, ui):
        self.key_exchange_gui = ui

    def progress_update(self, msg):
        self.indicator.set_status(msg)

    def check_perm_key(self):
        perm_key_fname = self.myself.get("key_fname")
        if not perm_key_fname:
            self.gen_perm_key()
        return False

    def show_key_management_gui(self):
        self.key_management_gui.run()

    def show_exchange_keys_gui(self, user):
        self.key_exchange_gui.run(user)

    def check_request(self, request):
        """ Check that the request we got was the next one in the protocol """
        state = self.current['state']
        return (request == self.KM_PROTOCOL_VIOLATION or
            request == self.KM_ERROR or
            request == self.KM_CANCEL or
            (state == None and request == self.KM_REQUEST_KEY) or
            (state == self.KM_REQUEST_KEY and request == self.KM_REQUEST_OK) or
            (state == self.KM_REQUEST_KEY and request == self.KM_REQUEST_DENIED) or
            (state == self.KM_REQUEST_OK and request == self.KM_TEMP_KEY_ACK) or
            (state == self.KM_TEMP_KEY_ACK and request == self.KM_TEMP_KEY2) or
            (state == self.KM_TEMP_KEY2 and request == self.KM_PERM_KEY2) or
            (state == self.KM_PERM_KEY2 and request == self.KM_FINISHED))

    def check_answer(self, answer):
        """ Check that the answer we got was for the request we sent """
        state = self.current['state']
        return (answer == self.KM_PROTOCOL_VIOLATION or
            answer == self.KM_ERROR or
            answer == self.KM_CANCEL or
            (state == self.KM_REQUEST_KEY and answer == self.KM_REQUEST_ACK) or
            (state == self.KM_REQUEST_KEY and answer == self.KM_REQUEST_NACK) or
            (state == self.KM_REQUEST_OK and answer == self.KM_REQUEST_ANSWER_ACK) or
            (state == self.KM_REQUEST_DENIED and answer == self.KM_REQUEST_ANSWER_ACK) or
            (state == self.KM_TEMP_KEY_ACK and answer == self.KM_TEMP_KEY1) or
            (state == self.KM_TEMP_KEY2 and answer == self.KM_PERM_KEY1) or
            (state == self.KM_PERM_KEY2 and answer == self.KM_PERM_KEY_ACK) or
            (state == self.KM_FINISHED and answer == self.KM_FINISHED))

    def send_exchange_request(self, user):
        """ Sends a request to perform key exchange """
        self.current['user'] = user
        self.send_request(user, self.KM_REQUEST_KEY)

    def send_request_answer(self, answer, user):
        """ Handles answers from dialog asking user to accept key exchange.
            This is called from the GUI """
        request = self.KM_REQUEST_OK if answer else self.KM_REQUEST_DENIED
        self.send_request(user, request)

    def save_symmetric_key(self, key, user):
        """ Saves to symmetric key passphrase typed in by the user.
            This is called from the GUI """
        self.temp_passphrase = key
        self.send_request(user, self.KM_TEMP_KEY_ACK)

    def send_cancel(self, user):
        if self.temp_key_watcher:
            self.temp_key_watcher.cancel()
            self.temp_key_watcher = None
        self.send_request(user, self.KM_CANCEL)

    def send_request(self, user, request, payload=''):
        cuser = self.current['user']
        if cuser == None:
            return
        if user != cuser:
            warning('keymanagement: Sending message to wrong uid %s while current uid is %s\n' % (user.get('uid'), cuser.get('uid')))
        self.current['state'] = request
        nick = user.get('nick')
        debug('Key management: sending request %s to %s\n' %(request, nick))
        request = {'t': request, 'uid': self.my_uid, 'param': payload}
        self.fetcher.fetch(user, PLUGIN_TYPE_KEY_MANAGEMENT, request,
            self.request_cb, user.get('uid'))

    def handle_requests(self, from_user, request):
        """ Handles requests from fetcher """
        if request == None:
            return
        if not validate({'t': str,
                         'uid': lambda s: type(s) == str and valid_uid(s) and s != self.my_uid,
                         'param': str}, request):
            debug('Key management: Broken request: %s\n' %(request))
            return {'r': self.KM_PROTOCOL_VIOLATION, uid: self.my_uid}
        cmd = request['t']
        uid = request['uid']
        param = request['param']

        debug('Key management: handling request %s from %s\n' %(cmd, uid))

        user = self.community.get_user(uid)
        if user != from_user:
            warning("keymanagement: Invalid uid from fetcher: %s\n" %(uid))
            return {'r': self.KM_PROTOCOL_VIOLATION, 'uid': self.my_uid}
        nick = user.get('nick')

        if self.current['user'] and user != self.current['user']:
            warning('keymanagement: Paraller request from %s: Current uid is %s\n' %(nick, self.current['user'].get('uid')))
            return {'r': self.KM_REQUEST_NACK, 'uid': self.my_uid}

        if not self.check_request(cmd):
            warning('keymanagement: Protocol violation from %s: Current state is %s but received request %s\n' %(nick, self.current['state'], cmd))
            return {'r': self.KM_PROTOCOL_VIOLATION, 'uid': self.my_uid}

        self.current['state'] = cmd

        self.key_exchange_gui.plugin_to_gui(user, cmd, True)

        payload = ''
        if cmd == self.KM_REQUEST_KEY:
            self.current['user'] = user
            result = self.KM_REQUEST_ACK
        elif cmd == self.KM_REQUEST_DENIED:
            debug('keymanagement: %s denied request for key exchange\n' %(nick))
            self.current = {'user': None, 'state': None}
            result = self.KM_CANCEL
        elif cmd == self.KM_REQUEST_OK:
            debug('keymanagement: started key exchange with %s\n' %(nick))
            result = self.KM_REQUEST_ANSWER_ACK
        elif cmd == self.KM_TEMP_KEY_ACK:
            # Other user has typed in the passphrase. We can now send the
            # temporary key encrypted with it.
            result = self.KM_TEMP_KEY1
            payload = self.sym_enc(self.load_pub_key(self.myself, temp=True),
                self.temp_passphrase)
            if not payload:
                result = self.KM_ERROR
                payload = ''
        elif cmd == self.KM_TEMP_KEY2:
            # Received other party's temporary key. Let's send our
            # permanent key encrypted with this temporary key.
            temp_key = self.sym_dec(param, self.temp_passphrase)
            if temp_key and self.save_key(user, pub=temp_key, temp=True):
                result = self.KM_PERM_KEY1
                payload = self.asym_enc(self.load_pub_key(self.myself),
                                        self.key_path(user, temp=True))
                if not payload:
                    result = self.KM_ERROR
                    payload = ''
            else:
                result = self.KM_ERROR
                payload = ''
        elif cmd == self.KM_PERM_KEY2:
            # Received permanent key. Save it and send "finished".
            perm_key = self.asym_dec(param, self.key_path(self.myself, temp=True))
            if perm_key and self.save_key(user, pub=perm_key):
                result = self.KM_PERM_KEY_ACK
            else:
                result = self.KM_ERROR
        elif cmd == self.KM_CANCEL:
            self.current = {'user': None, 'state': None}
            # Key exchange canceled
            result = self.KM_CANCEL
        elif cmd == self.KM_FINISHED:
            self.community.announce_user_change(user) # update user state
            self.current = {'user': None, 'state': None}
            # Successful key exchange
            result = self.KM_FINISHED
        elif cmd == self.KM_ERROR:
            self.current = {'user': None, 'state': None}
            result = self.KM_ERROR
        elif cmd == self.KM_PROTOCOL_VIOLATION:
            self.current = {'user': None, 'state': None}
            result = self.KM_PROTOCOL_VIOLATION

        debug('Key management: sending answer %s to %s\n' %(result, nick))
        return {'r': result, 'uid': self.my_uid, 'param': payload}

    def request_cb(self, target_user, request, ctx):
        """ Handles answers from fetcher """

        if request == None:
            return

        if not validate({'r': str,
                         'uid': lambda s: type(s) == str and valid_uid(s) and s != self.my_uid,
                         'param': str}, request):
            debug('Key management: Broken payload: %s\n' %(' '.join(payload)))
            return

        cmd = request['r']
        uid = request['uid']
        param = request['param']

        if uid == self.my_uid:
            return

        debug('Key management: got answer %s from %s\n' %(cmd, uid))
        user = self.community.get_user(uid)

        if self.current['user'] and user != self.current['user']:
            warning('keymanagement: Protocol violation from %s: Current uid is %s\n' %(nick, self.current['uid'].get('uid')))
            return {'r': self.KM_PROTOCOL_VIOLATION, 'uid': self.my_uid}

        if not self.check_answer(cmd):
            warning('keymanagement: Protocol violation from %s: request was %s but answer was %s' %(uid, self.current['state'], cmd))
            self.send_request(user, self.KM_PROTOCOL_VIOLATION, '')
            return

        self.key_exchange_gui.plugin_to_gui(user, cmd, False)

        payload = ''
        if cmd == self.KM_REQUEST_ACK:
            self.temp_key_watcher = self.gen_temp_key()
            self.temp_passphrase = self.gen_passphrase()
            debug('Key management: passphrase is %s\n' %(self.temp_passphrase))
            return
        if cmd == self.KM_REQUEST_ANSWER_ACK:
            self.gen_temp_key()
            return
        elif cmd == self.KM_TEMP_KEY1:
            # Received temporery key: save it and send our temporary key
            # encrypted with the symmetric cipher
            temp_key = self.sym_dec(param, self.temp_passphrase)
            if temp_key and self.save_key(user, pub=temp_key, temp=True):
                send_cmd = self.KM_TEMP_KEY2
                payload = self.sym_enc(self.load_pub_key(self.myself, temp=True),
                    self.temp_passphrase)
                if not payload:
                    send_cmd = self.KM_ERROR
                    payload = ''
            else:
                send_cmd = self.KM_ERROR
                payload = ''
        elif cmd == self.KM_PERM_KEY1:
            # Received counterpartys permanent key, so let's save it and send ours
            perm_key = self.asym_dec(param, self.key_path(self.myself, temp=True))
            if perm_key and self.save_key(user, pub=perm_key):
                send_cmd = self.KM_PERM_KEY2
                payload = self.asym_enc(self.load_pub_key(self.myself),
                                        self.key_path(user, temp=True))
                if not payload:
                    send_cmd = KM.ERROR
                    payload = ''
            else:
                send_cmd = KM_ERROR
                payload = ''
        elif cmd == self.KM_PERM_KEY_ACK:
            send_cmd = self.KM_FINISHED
        elif cmd == self.KM_FINISHED:
            # Successful key exchange
            self.current = {'user': None, 'state': None}
            self.community.announce_user_change(user) # update user state
            return
        elif cmd == self.KM_CANCEL:
            self.current = {'user': None, 'state': None}
            return
        elif cmd == self.KM_ERROR:
            self.current = {'user': None, 'state': None}
            return
        elif cmd == self.KM_PROTOCOL_VIOLATION:
            self.current = {'user': None, 'state': None}
            return
        elif cmd == self.KM_REQUEST_NACK:
            self.current = {'user': None, 'state': None}
            return

        self.current['state'] = send_cmd
        self.send_request(user, send_cmd, payload)

    def gen_passphrase(self):
        """ Returns random string using characters
            from set [a-z] with given length """
        return ''.join(
            random.sample(map(str, range(0,10)) +
                map(chr, range(ord('a'), ord('z') + 1)) +
                map(chr, range(ord('A'), ord('Z') + 1)), self.passphraselen))

    def gen_key_pair(self, keysize, cb):
        """ Generates asymmetric key pair.
            First generate private key and test if it succeeded.
            Then use private key to generate public key.
            If everything went well, call GUI's generate_keys_cb with
            the key pair, else call it with (None,None) """

        def gen_key_pair_pub_cb(data, ctx):
            if not data:
                warning('keymanagement: Could not generate a key pair\n')
                cb(None, None)
            else:
                cb(ctx, data)

        def gen_key_pair_priv_cb(data, ctx):
            if not data:
                warning('keymanagement: Could not generate a key pair\n')
                cb(None, None)
            else:
                xrun([self.sslname, 'rsa', '-pubout'], gen_key_pair_pub_cb,
                    data, data)

        return xrun([self.sslname, 'genrsa', str(keysize)],
            gen_key_pair_priv_cb, None)

    def gen_temp_key(self, keysize=1024):
        """ Generates temporary asymmetric key pair
            for encrypting permanent key """
        self.temp_session_key = [None, None]
        self.key_exchange_gui.generating_temp_key()
        return self.gen_key_pair(keysize, self.gen_temp_key_cb)

    def gen_temp_key_cb(self, priv, pub):
        self.temp_key_watcher = None
        self.key_exchange_gui.generated_temp_key()
        self.temp_session_key[0] = priv
        self.temp_session_key[1] = pub
        if priv and pub:
            self.save_key(self.myself, priv=self.temp_session_key[0],
                pub=self.temp_session_key[1], temp=True)

    def gen_perm_key(self, keysize=2048):
        self.key_management_gui.generate_perm_key_cb(False)
        self.gen_key_pair(keysize, self.gen_perm_key_cb)

    def gen_perm_key_cb(self, priv, pub):
        self.key_management_gui.generate_perm_key_cb(True)
        if priv and pub:
            self.save_key(self.myself, priv, pub)

    def key_hash(self, priv=None, pub=None):
        hash = sha1()
        if priv:
            hash.update(priv)
        if pub:
            hash.update(pub)
        return hash.hexdigest()

    def key_path(self, user, temp=False):
        if temp:
            fname = 'temp_key'
        else:
            fname = user.get('key_fname')
            if fname == None:
                return None
        return os.path.join(self.community.get_user_dir(user), fname)

    def save_key(self, user, priv=None, pub=None, temp=False):
        if not (priv or pub):
            warning('keymanagement: Could not save a key: pub and priv are None\n')
            return False

        if temp:
            key_path = self.key_path(user, temp=True)
        else:
            key_id = self.key_hash(priv, pub)
            key_fname = 'key_' + key_id
            key_path = os.path.join(self.community.get_user_dir(user), key_fname)

        try:
            f = open(key_path, 'w')
        except IOError:
            warning('keymanagement: Could not save a key: Could not open %s for writing\n' %(key_path))
        try:
            if priv:
                f.write(priv)
            if pub:
                f.write(pub)
        except IOError:
            warning('keymanagement: Could not save key: IOError while writing to %s\n' %(key_path))
            return False
        finally:
            f.close()

        if not temp:
            key_path = self.key_path(user)
            if key_path != None:
                xremove(key_path)

            user.set('key_fname', key_fname)

        return True

    def load_key(self, user, pub, priv, temp=False):
        key_path = self.key_path(user, temp)

        if pub:
            key = xsystem([self.sslname, 'rsa', '-pubout', '-in', key_path])
            if not key:
                warning('keymanagement: Could not load public key\n')
                return None
        if priv:
            key = xsystem([self.sslname, 'rsa', '-in', key_path])
            if not key:
                warning('keymanagement: Could not load private key\n')
                return None

        return key

    def load_pub_key(self, user, temp=False):
        return self.load_key(user, True, False, temp)

    def load_priv_key(self, user, temp=False):
        return self.load_key(user, False, True, temp)

    def sym_enc(self, plain, passphrase):
        """ Encrypts message with AES using given passphrase """
        ciph = xsystem([self.sslname, self.symmetric, '-e', '-pass', 'stdin'],
            passphrase + '\n' + plain)
        if not ciph:
            warning('keymanagement: Unable to perform symmetric encryption\n')
            return None
        return ciph

    def sym_dec(self, ciph, passphrase):
        """ Decrypts message with AES using given passphrase """
        (rfd, wfd) = xpipe()
        os.write(wfd, passphrase + '\n')
        plain = xsystem([self.sslname, self.symmetric, '-d', '-pass',
            'fd:' + str(rfd)], ciph)
        xclose(wfd)
        xclose(rfd)
        if not plain:
            warning('keymanagement: Unable to decrypt because %s does not exist\n' %(self.sslname))
            return None

        return plain

    def asym_enc(self, plain, keyfile):
        """ Encrypts message with given public key.
            This is done by creating a random key for symmetric cipher,
            encrypting that key with the public key and then using the
            symmetric key to encrypt the actual message. """
        f = open('/dev/urandom')
        passphrase = b64encode(f.read(64))
        f.close()

        ciphkey = xsystem([self.sslname, 'rsautl', '-encrypt', '-pubin',
            '-inkey', keyfile], passphrase)
        if not ciphkey:
            warning('keymanagement: Unable to perform asymmetric encryption\n')
            return None

        ciph = self.sym_enc(plain, passphrase)
        if not ciph:
            return None

        return str(len(ciphkey)) + '\0' + ciphkey + ciph

    def asym_dec(self, ciph, keyfile):
        """ Decrypts encrypted message with given private key.
            First decrypt the encrypted symmetric key with the private key
            and then decrypt the actual message with that symmetric key. """
        ciph = ciph.split('\0')
        ciphkey_len = int(ciph[0])
        ciph = '\0'.join(ciph[1:])
        ciphkey = ciph[:ciphkey_len]
        ciph = ciph[ciphkey_len:]

        passphrase = xsystem([self.sslname, 'rsautl', '-decrypt', '-inkey',
            keyfile], ciphkey)
        if not passphrase:
            warning('keymanagement: Unable to perform asymmetric decryption\n')
            return None

        return self.sym_dec(ciph, passphrase)
 
def init(options):
    Key_Management_Plugin()
