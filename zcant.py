#!/usr/bin/env python
"""
Main executable which launches the ZCANT GUI.

---------------
Myotisoft ZCANT
Copyright (C) 2012-2017 Myotisoft LLC, all rights reserved.
You may use, distribute, and modify this code under the terms of the MIT License.
"""

import sys
import errno
import os.path
import logging
import platform
from logging.handlers import RotatingFileHandler


LOG_MAX_FILESIZE_MB = 2
LOG_BACKUP_COUNT = 9
LOG_FMT = '%(asctime)s\t%(levelname)s\t%(message)s'
LOG_FILE = '~/.myotisoft/zcant/logs/zcant.log'


def configure_logging(logfilename, level=logging.DEBUG):
    """Configure application-level console and file-based logging"""

    # configure console logging...
    logging.basicConfig(level=level, format=LOG_FMT)

    # configure file-based logging
    logfilename = os.path.expanduser(logfilename)
    try:
        os.makedirs(os.path.dirname(logfilename))
    except OSError, e:
        if e.errno != errno.EEXIST:
            raise
    try:
        file_logger = RotatingFileHandler(logfilename, maxBytes=LOG_MAX_FILESIZE_MB*1024*1024, backupCount=LOG_BACKUP_COUNT)
        file_logger.setFormatter(logging.Formatter(LOG_FMT))
        file_logger.setLevel(level)
        logging.getLogger().addHandler(file_logger)  # root logger
    except Exception:
        log = logging.getLogger(__name__)
        log.exception('Failed while configuring logging!')


def zcant_gui():
    """Launch the ZCANT GUI"""
    import wx
    from zcant.gui import ZcantMainFrame

    app = wx.App(False)
    frame = ZcantMainFrame(None)
    frame.Maximize(True)
    frame.Show(True)
    app.MainLoop()


def main():
    """Main entrypoint"""
    configure_logging(LOG_FILE)
    log = logging.getLogger(__name__)
    log.debug('%s %s %s', platform.python_implementation(), platform.python_version(), platform.platform())
    try:
        zcant_gui()
    except Exception, e:
        log.exception('GUI initialization failed!')
        sys.exit(255)


if __name__ == '__main__':
    main()
