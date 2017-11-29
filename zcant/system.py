"""
ZCANT utils for interacting with the local OS outside of our own application

---------------
Myotisoft ZCANT
Copyright (C) 2012-2017 Myotisoft LLC, all rights reserved.
You may use, distribute, and modify this code under the terms of the MIT License.
"""

import os
import sys
import subprocess

import logging
log = logging.getLogger(__name__)


def launch_external(fname):
    """Launch a file using the preferred external program (eg. PDF with Acrobat)"""
    log.debug('Launching with external program: %s ...', fname)
    if sys.platform.startswith('darwin'):
        subprocess.call(('open', fname))
    elif os.name == 'nt':
        os.startfile(fname)
    elif os.name == 'posix':
        subprocess.call(('xdg-open', fname))


def browse_external(fname):
    """Browse a specified file using Windows Explorer, Finder, etc."""
    log.debug('Browsing to file: %s ...', fname)
    if sys.platform.startswith('darwin'):
        subprocess.call(('open', '-R', fname))
    elif os.name == 'nt':
        os.Popen(r'explorer /select,"%s"' % fname)
    elif os.name == 'posix':
        subprocess.call(('nautilus', fname))  # gnome only!
