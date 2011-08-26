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
from gobject import timeout_add_seconds
from datetime import datetime, timedelta
from os import listdir, remove
from os.path import join
from tempfile import mkstemp
from time import time

from ossupport import xclose
from plugins import Plugin, get_plugin_by_type
from support import die, warning
from proximateprotocol import PLUGIN_TYPE_SCHEDULER, PLUGIN_TYPE_COMMUNITY
from utils import str_to_int

# seconds
SCHEDULE_PERIOD = 5

class Periodic_Timer:
    def __init__(self, period, callback, ctx):
        assert((period % SCHEDULE_PERIOD) == 0)
        self.div = period // SCHEDULE_PERIOD
        self.callback = callback
        self.ctx = ctx
        self.step = 0

    def call(self, t):
        return self.callback(t, self.ctx)

    def test(self, t):
        self.step += 1
        if self.step != self.div:
            return True
        self.step = 0
        return self.call(t)

class Scheduler_Plugin(Plugin):

    # These constants can be used to represent time deltas (relative times)
    DAY = timedelta(1)
    SECOND = timedelta(0, 1)

    EXPIRE_PREFIX = 'expiringfile'

    def __init__(self):
        self.register_plugin(PLUGIN_TYPE_SCHEDULER)
        self.community = None

        self.callbacks = []
        self.periodic = []
        timeout_add_seconds(SCHEDULE_PERIOD, self.schedule)

    def call_at(self, dt, callback, ctx=None):
        """ Call callback(ctx) at dt, where dt is datetime.datetime object """
        self.callbacks.append((dt, callback, ctx))

    def call_in(self, rel, callback, ctx=None):
        """ Call callback(ctx) is a datetime.timedelta object """

        dt = datetime.now() + rel
        self.call_at(dt, callback, ctx)

    def call_periodic(self, period, callback, ctx=None, callnow=False):
        """ Install a periodic timer. Returns the timer iff it is
            installed, otherwise None.

            Period is a datetime.timedelta object. The period must be a
            multiple of SCHEDULE_PERIOD.

            The callback should return False or True. The timer is removed
            iff False is returned from the callback. The timer calls
            callback(t, ctx), where t is a time value returned by time.time().

            The timer is not installed if callnow == True and the first
            callback returns False. """

        secs = 3600 * 24 * period.days + period.seconds
        timer = Periodic_Timer(secs, callback, ctx)
        success = True
        if callnow:
            success = timer.call(time())
        if success:
            self.periodic.append(timer)
            return timer
        return None

    def parse_filename_datetime(self, name):
        fields = name.split('-')
        if len(fields) < 5:
            return None
        try:
            year = int(fields[1])
            month = int(fields[2])
            day = int(fields[3])
            secs = int(fields[4])
        except ValueError:
            return None
        hour = secs // 3600
        if hour >= 24:
            return None
        secs = secs % 3600
        minute = secs // 60
        second = secs % 60
        return datetime(year, month, day, hour, minute, second)

    def remove_garbage(self, t, ctx):
        now = datetime.now()
        dname = self.community.get_user_dir()
        for fname in listdir(dname):
            if not fname.startswith(self.EXPIRE_PREFIX):
                continue
            path = join(dname, fname)
            dt = self.parse_filename_datetime(fname)
            if dt == None:
                warning('Bad expiring file name, just remove it: %s\n' % path)
            if dt == None or dt <= now:
                try:
                    remove(path)
                    warning('Garbage collected %s\n' % path)
                except OSError:
                    warning('Could not delete %s\n' % path)
        return True

    def get_expiring_file(self, dt=None, rel=None):
        """ Create a temp file, which expires at a given time. The temp file
            is stored under user's proximate directory. The file will expire
            (be deleted) after the given time. The actual deletion time is
            not very accurate.

            dt is a point in time, which is an instance of datetime.datetime.
            If dt == None, it is assumed to be now. If rel == None,
            it is assumed to be zero. Otherwise it is assumed to be a
            relative delay with respect to dt.
            rel is an instance of datetime.timedelta.

            Hint: Use scheduler.DAY and scheduler.SECOND to specify relative
            times """

        assert(dt == None or isinstance(dt, datetime))
        assert(rel == None or isinstance(rel, timedelta))

        if dt == None:
            dt = datetime.now()
        if rel != None:
            dt = dt + rel
        # ISO date: YYYY-MM-DD-s, where s is a number of seconds in the day
        isodate = str(dt.date())
        seconds = str(dt.hour * 3600 + dt.minute * 60 + dt.second)
        prefix = '%s-%s-%s-' % (self.EXPIRE_PREFIX, isodate, seconds)
        directory = self.community.get_user_dir()
        try:
            (fd, fname) = mkstemp(prefix=prefix, dir=directory)
        except OSError:
            warning('expiring_file: mkstemp() failed\n')
            return None
        xclose(fd)
        return fname

    def ready(self):
        self.community = get_plugin_by_type(PLUGIN_TYPE_COMMUNITY)

        # Cleanup garbage files every 5 mins
        self.call_periodic(300 * self.SECOND, self.remove_garbage)

    def remove_periodic(self, timer):
        self.periodic.remove(timer)

    def schedule(self):
        now = datetime.now()
        i = 0
        while i < len(self.callbacks):
            (t, callback, ctx) = self.callbacks[i]
            if now >= t:
                callback(ctx)
                self.callbacks.pop(i)
            else:
                i += 1

        t = time()
        i = 0
        while i < len(self.periodic):
            if not self.periodic[i].test(t):
                self.periodic.pop(i)
                continue
            i += 1

        return True

def init(options):
    Scheduler_Plugin()
