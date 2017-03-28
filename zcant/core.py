"""
Core high-level ZCANT functionality which is distinct from the GUI itself.

---------------
Myotisoft ZCANT
Copyright (C) 2012-2017 Myotisoft LLC, all rights reserved.
You may use, distribute, and modify this code under the terms of the MIT License.
"""

import os.path
from bisect import bisect
from threading import Thread

from zcant import print_timing
from zcant.anabat import extract_anabat, AnabatFileWriter
from zcant.conversion import wav2zc

from guano import GuanoFile

import numpy as np

import wx

import logging
log = logging.getLogger(__name__)

np.seterr(all='warn')  # switch to 'raise' and NumPy will fail fast on calculation errors


class ZeroCross(object):
    """Represents a zero-cross signal.

    A ZC object supports many of the same features as a list or array. For example:
        if not zc:
            pass
        subset = zc[:100]
        len(zc)
    """
    def __init__(self, times, freqs, amplitudes, metadata):
        if len(times) != len(freqs):
            raise ValueError('times (%d) and freqs (%d) disagree' % (len(times), len(freqs)))
        if amplitudes is not None and len(times) != len(amplitudes):
            raise ValueError('times (%d) and amplitudes (%d) disagree' % (len(times), len(amplitudes)))
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
        """Does this signal support amplitude values?"""
        return self.amplitudes is not None

    @property
    def duration(self):
        """The duration of this signal in seconds"""
        if self.times is None or len(self.times) < 2:
            return -0
        return self.times[-1] - self.times[0]

    def get_slopes(self, smooth=False, max_slope=5000):
        """Calculate slope values, optionally smoothing them to reduce noise"""
        slopes = _slopes(self.times, self.freqs, max_slope)
        if smooth:
            slopes = _smooth(slopes)
        return slopes

    def get_pulses(self, time_gap=0.01):
        """Produce the indexes which mark the start of each pulse (DUMB IMPLEMENTATION!)

        :param time_gap: time in seconds, a silence gap of at least this length results in a
                         new pulse (default is 10ms of silence)
        """
        diffs = np.diff(self.times)
        splits = np.where(diffs > time_gap)[0]  # any time gap larger than 10ms
        # TODO: check for minimum number of dots in a pulse? max frequency jump between dots?
        return splits

    def windowed(self, start, duration):
        if len(self.times) < 2:
            return self  # FIXME: shouldn't we instead return an empty ZC if no dots in window?

        if self.times[-1] - start >= duration:  # normal
            window_from, window_to = bisect(self.times, start), bisect(self.times, start + duration)
        elif duration >= self.times[-1]:  # window too big
            window_from, window_to = 0, len(self.times)-1
        else:  # EOF
            window_from, window_to = bisect(self.times, self.times[-1] - duration), len(self.times)-1  # panned to the end

        zc = self[window_from:window_to]

        # because times is sparse, we need to fill in edge cases (unfortunately np.insert, np.append copy rather than view)
        if len(zc) == 0 or zc.times[0] > start:
            zc.times, zc.freqs = np.insert(zc.times, 0, start), np.insert(zc.freqs, 0, start)
            zc.amplitudes = np.insert(zc.amplitudes, 0, start) if zc.supports_amplitude else None
        if zc.times[-1] < start + duration:
            zc.times, zc.freqs = np.append(zc.times, start + duration), np.append(zc.freqs, 0)  # this is wrong for END OF FILE case
            zc.amplitudes = np.append(zc.amplitudes, 0) if zc.supports_amplitude else None  # ?

        log.debug('%.1f sec window:  %s', duration, zc)
        return zc

    def __repr__(self):
        return '<ZeroCross dots=%d duration=%0.2fsec>' % (len(self.times), self.duration)


@print_timing
def _smooth(slopes):
    """
    Smooth slope values to account for the fact that zero-cross conversion may be noisy.
    :param slopes: slope values
    :return:
    TODO: smooth individual pulses independently so we don't smooth across their boundaries
    """
    WINDOW_SIZE = 3  # hard-coded for now
    if slopes.size <= WINDOW_SIZE:
        return np.zeros(slopes.size)
    # Rather than true convolution, we use a much faster cumulative sum solution
    # http://stackoverflow.com/a/11352216
    # http://stackoverflow.com/a/34387987
    slopes = np.where(np.isnan(slopes), 0, slopes)  # replace NaN values
    cumsum = np.cumsum(np.insert(slopes, 0, 0))
    smoothed = (cumsum[WINDOW_SIZE:] - cumsum[:-WINDOW_SIZE]) / WINDOW_SIZE
    # smoothed is missing element at start and end, so fake 'em
    smoothed = np.insert(smoothed, 0, smoothed[0])
    smoothed = np.insert(smoothed, -1, smoothed[-1])
    return smoothed


@print_timing
def _slopes(x, y, max_slope=5000):
    """
    Produce an array of slope values in octaves per second.
    We very, very crudely try to compensate for the jump between pulses, but don't deal well with noise.
    :param x:
    :param y:
    :return:
    """
    if not len(x) or not len(y):
        return np.array([])
    elif len(x) == 1:
        return np.array([0.0])

    if not np.any(y):
        y_octaves = y
    else:
        # calculation for difference wil be same in Hz or kHz, so no need to convert
        y_octaves = np.log2(y)
        y_octaves[np.isnan(y_octaves)] = 0.0
    slopes = np.diff(y_octaves) / np.diff(x)
    slopes = np.append(slopes, slopes[-1])  # FIXME: hack for final dot (instead merge slope(signal[1:]) and slope(signal[:-1])
    slopes = np.abs(slopes)  # Analook inverts slope so we do also (but should we keep the distinction between positive and negative slopes??)
    log.debug('Smax: %.1f OPS   Smin: %.1f OPS', np.amax(slopes), np.amin(slopes))

    slopes[slopes > max_slope] = 0.0  # super-steep is probably noise or a new pulse
    slopes[np.isnan(slopes)] = 0.0

    # TODO: integrate out-of-bounds detection (or pulse splitting) with smoothing to prevent smoothing across pulse boundaries
    # FIXME: rather than smoothing after the fact, can we simply calculate slope initially across every 2nd element (moving window)?

    return slopes



class MainThread(Thread):
    """Main wave-to-zerocross extraction thread"""

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


class AnabatFileWriteThread(Thread):
    """Thread for writing an Anabat-format file"""

    def __init__(self, zc, fname, divratio):
        Thread.__init__(self)
        self.zc = zc
        self.fname = fname
        self.divratio = divratio

        self.setDaemon(True)
        self.start()  # start immediately

    def run(self):
        md = self.zc.metadata
        timestamp = md.get('timestamp', None)
        species = md.get('species', '')
        note1 = md.get('note1', '')
        if note1:
            note2 = 'Myotisoft ZCANT'
        else:
            note1, note2 = 'Myotisoft ZCANT', ''
        if self.zc.supports_amplitude:
            log.debug('Adding GUANO metadata :-)')
            guano = GuanoFile()
            guano['ZCANT|Amplitudes'] = self.zc.amplitudes
        else:
            log.debug('Not adding GUANO metadata :-(')
            guano = None

        log.debug('Saving %s ...', self.fname)

        outdir = os.path.dirname(self.fname)
        if not os.path.exists(outdir):
            log.debug('Creating outdir %s ...', outdir)
            os.makedirs(outdir)

        with AnabatFileWriter(self.fname) as out:
            out.write_header(timestamp, self.divratio, species=species, note1=note1, note2=note2, guano=guano)
            time_indexes_us = self.zc.times * 1000000
            intervals_us = np.diff(time_indexes_us)
            intervals_us = intervals_us.astype(int)  # TODO: round before int cast; consider casting before diff for performance
            out.write_intervals(intervals_us)
