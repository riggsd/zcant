"""
Core high-level ZCANT functionality which is distinct from the GUI itself.

---------------
Myotisoft ZCANT
Copyright (C) 2012-2017 Myotisoft LLC, all rights reserved.
You may use, distribute, and modify this code under the terms of the MIT License.
"""

import os.path
from threading import Thread

from zcant.anabat import extract_anabat, AnabatFileWriter
from zcant.conversion import wav2zc

import wx

import logging
log = logging.getLogger(__name__)


class ZeroCross(object):
    """Represents a zero-cross signal"""

    def __init__(self, times, freqs, amplitudes, metadata):
        self.times = times
        self.freqs = freqs
        self.amplitudes = amplitudes
        self.metadata = metadata

    def __getitem__(self, slice):
        amplitudes = self.amplitudes[slice] if self.supports_amplitude else None
        return ZeroCross(self.times[slice], self.freqs[slice], amplitudes, self.metadata)

    def __len__(self):
        return len(self.times)

    @property
    def supports_amplitude(self):
        return self.amplitudes is not None

    @property
    def duration(self):
        return self.times[-1]


class MainThread(Thread):

    def __init__(self, parent_cb, path, **kwargs):
        Thread.__init__(self)
        self.parent_cb = parent_cb
        self.path = path
        self.filename = os.path.basename(path)
        self.kwargs = kwargs

        self.setDaemon(True)
        self.start()  # start immediately

    def extract(self, path):
        """Extract (times, freqs, amplitudes, metadata) from supported filetypes"""
        ext = os.path.splitext(path)[1].lower()
        if ext.endswith('#') or ext == '.zc':
            return extract_anabat(path, **self.kwargs)
        elif ext == '.wav':
            return wav2zc(path, **self.kwargs)
        else:
            raise Exception('Unknown file type: %s', path)

    def run(self):
        result = None
        try:
            times, freqs, amplitudes, metadata = self.extract(self.path)

            metadata['path'] = self.path
            metadata['filename'] = self.filename
            log.debug('    %s:  times: %d  freqs: %d', self.filename, len(times), len(freqs))

            result = ZeroCross(times, freqs, amplitudes, metadata)
        except Exception, e:
            log.exception('Barfed loading file: %s', self.path)
        wx.CallAfter(self.parent_cb, result)
