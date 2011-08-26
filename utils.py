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
from datetime import datetime, timedelta
import gtk
import random
from time import localtime, strftime, time, mktime
from gobject import timeout_add, GError
import zlib

class ETA:
    """ A class for computing estimated time of arrival (ETA) """

    def __init__(self, total, start = 0, interval = 1):
        self.total = total
        self.current = start
        self.interval = interval
        self.n = 5
        self.t = [time() - 1] * self.n
        self.p = [self.current] * self.n

    def partial(self):
        return self.current < self.total

    def update(self, increment):
        self.current += increment

        t = time()
        lt = self.t[-1]
        if t < (lt + self.interval):
            if t < lt:
                # Clock went backwards, reset ETA state
                self.t = [t] * self.n
                self.p = [self.current] * self.n
            return (None, None, None)

        self.t = self.t[1:] + [t]
        self.p = self.p[1:] + [self.current]

        dt = max(1.0, self.t[-1] - self.t[0])
        v = (self.p[-1] - self.p[0]) / dt

        # Return ETA in seconds as an integer value
        if v < 1:
            eta = 1000000
        else:
            eta = int(round((self.total - self.current) / v))

        # It is possible that current > total
        p = min(1.0, float(self.current) / self.total)

        return (eta, v, p)

class Rate_Limiter:
    def __init__(self, min_interval):
        self.min_interval = min_interval
        self.blocked = False

    def check(self):
        if self.blocked:
            return False
        timeout_add(self.min_interval * 1000, self.clear_blocked)
        self.blocked = True
        return True

    def clear_blocked(self):
        self.blocked = False
        return False

def check_image(fname):
    """ Tries to open an image file. If GError exception is caught
    returns False. """

    try:
        image = gtk.gdk.pixbuf_new_from_file(fname)
    except GError:
        return False

    return True

def cut_text(s, length):
    """ Cuts text to given length and adds three dots to the end. """
    if len(s) > length:
        s = s[:(length - 3)] + '...'
    return s

def decompress_with_limit(data, maxsize):
    decobj = zlib.decompressobj()
    try:
        data = decobj.decompress(data, maxsize)
    except zlib.error:
        return None
    if len(decobj.unconsumed_tail) > 0:
        return None
    return data

def del_integer_key(d, x):
    ret = d.has_key(x)
    if ret:
        del d[x]
    return ret

def format_bytes(x):
    if x < 500:
        return '%d B' % x
    for prefix in ('kB', 'MB', 'GB', 'TB', 'PB'):
        x /= 1000.
        if x < 500 or prefix == 'PB':
            return '%.1f %s' % (x, prefix)
    assert(False)

def iso_date_time(t=None, dispdate=True, disptime=True, dispsecs=False):
    """ Returns local time by default. t is the time_t value. """
    fmtl = []
    if dispdate:
        fmtl.append('%Y-%m-%d')
    if dispsecs:
        fmtl.append('%H:%M:%S')
    elif disptime:
        fmtl.append('%H:%M')
    fmt = ' '.join(fmtl)
    if t == None:
        return strftime(fmt)
    return strftime(fmt, localtime(t))

def n_lists(sequence, n):
    lists = []
    for i in range(0, len(sequence), n):
        lists.append(sequence[i : (i + n)])
    return lists

def new_integer_key(d):
    # Use zero on the first time
    if len(d) == 0:
        d[0] = None
        return 0

    keys = d.keys()
    xmin = min(keys)
    # Use zero whenever possible
    if xmin > 0:
        d[0] = None
        return 0

    xmax = max(keys)

    # Try a random key between min and max
    x = random.randint(xmin, xmax)
    if d.has_key(x) == False:
        d[x] = None
        return x

    x = xmax + 1
    d[x] = None
    return x

def now():
    """ Return current time in datetime format. Remove microseconds and tzinfo.
    """
    dt = datetime.now()
    f = dt.timetuple()
    return datetime(f[0], f[1], f[2], f[3], f[4], f[5])

def peel_string_prefix(s, prefix):
    if s.startswith(prefix) == False:
        return None
    return s[len(prefix):]

def pretty_line(msg, n):
    assert(n > 0)
    words = msg.split(' ')
    newwords = []
    linelength = 0
    for i in xrange(len(words)):
        word = words[i]
        linelength += len(word) + 1
        if i > 0 and linelength > n:
            newwords.append('\n')
            linelength = 0
        newwords.append(word)
    return ' '.join(newwords)

def random_hexdigits(nbits):
    assert((nbits % 4) == 0)
    ndigits = nbits // 4
    l = []
    for i in xrange(ndigits):
        l.append('%x' %(random.randint(0, 15)))
    return ''.join(l)

def read_file_contents(fname):
    if fname == None:
        return None
    try:
        f = open(fname, 'r')
    except IOError, (errno, strerror):
        return None
    blob = f.read()
    f.close()
    return blob

# Relative time thresholds are not exact, but it is not very important as it
# is used to present a relative time in human readable form.
reltimethresholds = ((3600*24*30*12, 'year'),
                     (3600*24*30, 'month'),
                     (3600*24*7, 'week'),
                     (3600*24, 'day'),
                     (3600, 'hour'),
                     (60, 'minute'),
                     (1, 'second'),
                    )

def relative_time_string(t):
    l = []
    d = time() - t
    future = (d < 0)
    if future:
        d = -d
        l.append('in')
    if d < 1:
        return 'now'
    for (threshold, unit) in reltimethresholds:
        if d >= threshold:
            break
    mult = int(round((10 * d) / threshold))
    if mult % 10 == 0:
        val = '%d' %(mult / 10)
    else:
        val = '%d.%d' %(mult / 10, mult % 10)
    if mult != 10:
        unit = unit + 's'
    l.append(val)
    l.append(unit)
    if not future:
        l.append('ago')
    return ' '.join(l)

def remove_all(l, item):
    i = 0
    while i < len(l):
        if l[i] == item:
            l.pop(i)
        else:
            i += 1

def separated_string_list(s, char):
    """ Return a list of non-empty strings separated with a given character """

    fields = s.split(char)
    l = []
    for s in fields:
        s = s.strip()
        if len(s) > 0:
            l.append(s)
    return l

def stepsafexrange(start, stop, step=1):
    """ stepsafexrange() is like xrange(), but it guarantees that the last
    index i in the range is such that (i + step) <= stop. In other words,
    if (stop - start) is not divisible by step, one index is left from the
    result what xrange() would return. This is used to avoid buffer
    overruns. """

    l = list(xrange(start, stop, step))
    if ((stop - start) % step != 0) and (len(l) > 0):
        l.pop()
    return l

def str_timet_to_datetime(s):
    t = str_to_int(s, None)
    if t == None:
        return None
    return timet_to_datetime(t)

def str_timet_to_iso_date_time(s, dispdate=True, disptime=True, dispsecs=False):
    t = str_to_int(s, None)
    if t == None:
        return None
    return iso_date_time(t, dispdate, disptime, dispsecs)

def str_to_datetime(datetimestr):
    """ Accept time stamps in format [YY-MM-DD] [HH:MM[:SS]] or +X, where
    X is an integer that specifies time relative to this moment. """

    if len(datetimestr) == 0:
        # if string is empty, return current time stamp
        return now()

    if datetimestr[0] == '+':
        s = str_to_int(datetimestr[1:], None)
        if s == None:
            return None
        return now() + timedelta(0, s)

    if datetimestr.find('-') == -1:
        # If date is not given, use today's date
        datetimestr = strftime('%Y-%m-%d') + ' ' + datetimestr

    t = None
    for lastpart in ['%H:%M:%S', '%H:%M', '%H', '']:
        fmt = '%Y-%m-%d'
        if len(lastpart) > 0:
            fmt += ' ' + lastpart
        try:
            t = datetime.strptime(datetimestr, fmt)
            break
        except ValueError:
            t = None

    if t == None:
        warning('Format error: %s is not a valid timestamp\n' %(datetimestr))

    return t

def str_to_int(s, invalidvalue):
    try:
        x = int(s)
    except ValueError:
        x = invalidvalue
    return x

def str_to_timet(datetimestr):
    dt = str_to_datetime(datetimestr)
    if dt == None:
        return None
    return mktime(dt.timetuple())

def str_triple_to_int(sx, sy, sz, invalidvalue):
    try:
        x = int(sx)
        y = int(sy)
        z = int(sz)
    except ValueError:
        x = invalidvalue
        y = invalidvalue
        z = invalidvalue
    return (x, y, z)

def strip_extra_slashes(path):
    """ Strip extra slashes from a filename. Examples:
    '//'  -> '/'
    '/'   -> '/'
    ''    -> ''
    'a//' -> 'a' """

    l = []
    slash = False
    for c in path:
        isslash = (c == '/')
        if not isslash or not slash:
            l.append(c)
        slash = isslash
    if slash and len(l) > 1 and l[-1] == '/':
        l.pop()
    return ''.join(l)

def time_compare(a, b=None):
    """ Compare datetime objects a and b. If a < b, that is, a means time
        before b, return -1. If b < a, return 1. Otherwise return 0.

        If b is not given, assume b is now. """

    if b == None:
        b = datetime.now()
    if a < b:
        return -1
    if b < a:
        return 1
    return 0

def time_expired(dt):
    return time_compare(dt) > 0

def timet_to_datetime(t):
    try:
        dt = datetime.fromtimestamp(t)
    except ValueError:
        dt = None
    return dt

def unique_elements(iterable):
    """ Return unique elements from an iterable object. The elements must be
    hashable (insertable into dictionary). """

    d = {}
    for e in iterable:
        d[e] = None
    return d.keys()
