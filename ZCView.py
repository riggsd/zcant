#!/usr/bin/env python
"""
Main executable which launches the ZCANT GUI.

---------------
Myotisoft ZCANT
Copyright (C) 2012-2017 Myotisoft LLC, all rights reserved.
You may use, distribute, and modify this code under the terms of the MIT License.
"""

import sys
import logging

import wx

from zcview.gui import ZCViewMainFrame


__version__ = '0.1a'


def main():
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s\t%(levelname)s\t%(message)s')

    app = wx.App(False)
    frame = ZCViewMainFrame(None)
    frame.Maximize(True)
    frame.Show(True)
    app.MainLoop()


if __name__ == '__main__':
    main()
