#!/usr/bin/env python

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
