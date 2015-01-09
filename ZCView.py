#!/usr/bin/env python

import sys
import logging

import wx

from zcview.gui import ZCViewMainFrame


def main():
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s\t%(levelname)s\t%(message)s')
    app = wx.App(False)
    frame = ZCViewMainFrame(None)
    frame.Show(True)
    app.MainLoop()


if __name__ == '__main__':
    main()
