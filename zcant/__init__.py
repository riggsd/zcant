"""
Misc. package-level utilities.

---------------
Myotisoft ZCANT
Copyright (C) 2012-2017 Myotisoft LLC, all rights reserved.
You may use, distribute, and modify this code under the terms of the MIT License.
"""

import time
import logging
log = logging.getLogger(__name__)


__version__ = '0.1a'


def print_timing(func):
    """Debug decorator for logging the time in milliseconds a function takes to execute"""
    def wrapper(*args, **kwargs):
        t1 = time.time()
        res = func(*args, **kwargs)
        t2 = time.time()
        log.debug('%06.1f ms %s', (t2-t1)*1000.0, func.func_name)
        return res
    return wrapper
