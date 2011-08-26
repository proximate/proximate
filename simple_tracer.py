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
#!/usr/bin/env python
import os
import sys
import traceback
import inspect
import runpy


def traceit(frame, event, arg):
    """ Trivial function call tracer. Use with sys.settrace(traceit). """
    if event == "call":
        stack = traceback.extract_stack(frame)
        filename, linenumber, funcname, text = stack[-1]
        args = inspect.getargvalues(frame)
        indent = len(stack) * " "
        filename = os.path.basename(filename)
        # Lots of stuff have broken __repr__.
        try:
            argvalues = inspect.formatargvalues(*args)
        except Exception, e:
            # TODO write an error message that accurately blames the culprit
            argvalues = "<BROKEN REPR>"

        print "%s%s:%s%s" % (indent, filename, funcname, argvalues)

    return traceit

if __name__ == "__main__":
    # Can be called with python -m simple_tracer your_module.
    # TODO: python -m simple_tracer path/to/your_script.py
    sys.argv.pop(0)
    script = sys.argv[0]
    sys.settrace(traceit)
    runpy.run_module(script)

