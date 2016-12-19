"""
Refactored ZCANT algorithm for conversion of .WAV to generic zero-crossing data
"""

#
# TODO: consider interpolating zero-cross values for increased accuracy
# https://gist.github.com/255291
#

from __future__ import division

import io
import sys
import wave
import struct
import os.path
import re
from datetime import datetime

import numpy as np
import scipy.signal

import logging
log = logging.getLogger(__name__)

from zcview import print_timing


__all__ = 'wav2zc'



# def lerp(i1, val1, i2, val2):
#     """Linear interpolation between two samples; returns interpolated interval at zero-crossing"""
#     return i1 - val1 * ((i2 - i1) / float(val2 - val1))


@print_timing
def rms(signal):
    """Calculate the Root-Mean-Square (RMS) value of a signal"""
    return np.sqrt(np.mean(np.square(signal)))


@print_timing
def load_wav(fname):
    """Produce (samplerate, signal) from a .WAV file"""
    try:
        wav = wave.open(fname, 'rb')
    except RuntimeError, e:
        # Python's chunk.py raises the RuntimeError *type* instead of an instance
        # This arcane bug is triggered by SonoBat example file CCK-13Aug01-828-TabrBzz.wav
        raise Exception('Failed opening .wav file for read (confusing offsets?)')

    w_nchannels, w_sampwidth, w_framerate_hz, w_nframes, w_comptype, w_compname = wav.getparams()
    if w_nchannels > 1:
        raise Exception('Only MONO .wav files are supported!')  # TODO
    if w_sampwidth != 2:
        raise Exception('Only 16-bit .wav files are supported (not %d)' % (w_sampwidth*8))  # TODO

    if w_framerate_hz <= 48000:
        log.debug('Assuming 10X time-expansion for file with samplerate %.1fkHz', w_framerate_hz/1000.0)
        w_framerate_hz *= 10

    # TESTING
    #w_framerate_hz /= 2

    wav_bytes = wav.readframes(w_nframes)
    wav.close()

    # Pettersson metadata is in the actual data chunk of the .wav file! Strip it out.
    skip_bytes = 0
    if wav_bytes[0xC4:0xC9] == 'D500X':
        log.debug('Stripping D500X metadata from audio frames.')
        skip_bytes = 0x3D4  # 0x1D4 for version 1.X firmware??
    elif wav_bytes[0xC4:0xCA] == 'D1000X':
        log.debug('Stripping D1000X metadata from audio frames.')
        skip_bytes = 0xF4
    if skip_bytes:
        wav_bytes = wav_bytes[skip_bytes:]
        w_nframes -= skip_bytes / w_sampwidth
        log.debug('expected frames: %d  actual frames: %d', w_nframes, len(wav_bytes)/16)

    signal = np.array(struct.Struct('<%dh' % w_nframes).unpack_from(wav_bytes), dtype=np.dtype('int16'))
    # signal = signal / (2 ** (16-1))  # convert from 16-bit int to float range -1.0 - 1.0
    return w_framerate_hz, signal


@print_timing
def highpassfilter(signal, samplerate, cutoff_freq_hz, filter_order=6):
    cutoff_ratio = cutoff_freq_hz / (samplerate / 2.0)
    b, a = scipy.signal.butter(filter_order, cutoff_ratio, btype='high')
    return scipy.signal.filtfilt(b, a, signal)


@print_timing
def noise_gate(signal, threshold_factor):
    threshold = threshold_factor * rms(signal)
    log.debug('RMS: %.1f  threshold: %0.1f' % (threshold, rms(signal)))
    # ignore everything below threshold amplitude (and convert whole signal to DC!)
    signal[signal < threshold] = 0
    return signal


@print_timing
def zero_cross(signal, samplerate, divratio):
    """Produce times (seconds) and frequencies (Hz) from calculated zero crossings"""
    # straight zero-cross without any samplerate interpolation
    crossings = np.where(np.diff(np.sign(signal)))[0][::divratio*2]  # indexes
    log.debug('Extracted %d crossings' % len(crossings))
    # crossings = np.array([i - signal[i] / (signal[i+1] - signal[i]) for i in crossings])  # interpolate  # FIXME: this is slow
    times_s = crossings / samplerate
    intervals_s = np.ediff1d(times_s, to_end=0)  # TODO: benchmark, `diff` may be faster than `ediff1d` (but figure out if the 0 appended to end is necessary?)
    freqs_hz = 1 / intervals_s * divratio
    freqs_hz[freqs_hz == np.inf] = 0  # fix divide-by-zero
    return times_s, freqs_hz


@print_timing
def hpf_zc(times_s, freqs_hz, cutoff_freq_hz):
    hpf_mask = np.where(freqs_hz > cutoff_freq_hz)
    junk_count = len(freqs_hz) - np.count_nonzero(hpf_mask)
    log.debug('Throwing out %d dots of %d (%.1f%%)' % (junk_count, len(freqs_hz), junk_count/len(freqs_hz)*100))
    return times_s[hpf_mask], freqs_hz[hpf_mask]


@print_timing
def wav2zc(fname, divratio=8, hpfilter_khz=20, threshold_factor=1.0, interpolate=False):
    """Convert a single .wav file to Anabat format.
    fname: input filename
    divratio: ZCAIM frequency division ratio (4, 8, 10, 16, or 32)
    hpfilter_khz: frequency in KHz of 6th-order high-pass butterworth filter; `None` or 0 to disable HPF
    threshold_factor: RMS multiplier for noise floor, applied after filter
    interpolate: use experimental dot interpolation or not (TODO: use upsampling instead)
    """

    log.debug('wav2zc(infile=%s, divratio=%d, hpf=%.1fKHz, threshold=%.1fxRMS)', fname, divratio, hpfilter_khz, threshold_factor)

    # check params
    if divratio not in (4, 8, 10, 16, 32):
        raise Exception('Unsupported divratio: %s (Anabat132 supports 4, 8, 10, 16, 32)' % divratio)

    samplerate, signal = load_wav(fname)
    if hpfilter_khz:
        signal = highpassfilter(signal, samplerate, hpfilter_khz*1000)
    signal = noise_gate(signal, threshold_factor)
    times_s, freqs_hz = zero_cross(signal, samplerate, divratio)
    times_s, freqs_hz = hpf_zc(times_s, freqs_hz, hpfilter_khz*1000)

    if len(freqs_hz) > 16384:  # CFC Read buffer max
        log.warn('File exceeds max dotcount (%d)! Consider raising DivRatio?', len(freqs_hz))

    min_, max_ = np.amin(freqs_hz) if freqs_hz.any() else 0, np.amax(freqs_hz) if freqs_hz.any() else 0
    log.debug('%s\tDots: %d\tMinF: %.1f\tMaxF: %.1f', os.path.basename(fname), len(freqs_hz), min_, max_)

    metadata = dict(divratio=divratio, date=extract_timestamp(fname))
    return times_s, freqs_hz, metadata


TIMESTAMP_REGEX = re.compile(r'(\d{8}_\d{6})')

def extract_timestamp(fname):
    # For now we simply yank from the filename itself, no proper metadata support
    try:
        timestamp = TIMESTAMP_REGEX.search(fname).groups()[0]
        return datetime.strptime(timestamp, '%Y%m%d_%H%M%S')
    except:
        return None


def _main(fname):
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s\t%(levelname)s\t%(message)s')
    #for fname in sys.argv[1:]:
    #	print fname
    #	print AnabatMetadata(fname)
    start_time = time.time()
    outfname = fname.rsplit('.',1)[0] + '.00#'
    wav2zc(fname)
    now = time.time()
    log.debug('Conversion time: %.2fs', now - start_time)


if __name__ == '__main__':
    import sys
    _main(sys.argv[1])
