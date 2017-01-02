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
def dc_offset(signal):
    """Correct DC offset"""
    log.debug('DC offset before: %.1f', np.sum(signal) / len(signal))
    signal -= signal.sum(dtype=np.int64) / len(signal)
    log.debug('DC offset after:  %.1f', np.sum(signal) / len(signal))
    return signal


@print_timing
def highpassfilter(signal, samplerate, cutoff_freq_hz, filter_order=6):
    """Full spectrum high-pass filter (butterworth)"""
    cutoff_ratio = cutoff_freq_hz / (samplerate / 2.0)
    b, a = scipy.signal.butter(filter_order, cutoff_ratio, btype='high')
    return scipy.signal.filtfilt(b, a, signal)


@print_timing
def noise_gate(signal, threshold_factor):
    """Discard low-amplitude portions of the signal.
    threshold_factor: ratio of root-mean-square "noise floor" below which we drop
    """
    signal_rms = rms(signal)
    threshold = threshold_factor * signal_rms
    log.debug('RMS: %.1f  threshold: %0.1f (%.1f x RMS)' % (signal_rms, threshold, threshold_factor))
    # ignore everything below threshold amplitude (and convert whole signal to DC!)
    signal[signal < threshold] = 0

    # experimental alternate method: shrink everything toward zero (broken!)
    #signal[np.logical_and(threshold > signal, signal > 0.0)] = 0.0
    #signal[signal >= threshold] -= threshold
    #signal[np.logical_and(-threshold < signal, signal < 0.0)] = 0
    #signal[signal <= -threshold] += threshold

    return signal


@print_timing
def interpolate(signal, crossings):
    """
    Calculate float crossing values by linear interpolation rather than relying exclusively
    on factors of samplerate. We find the sample values before and after the
    theoretical zero-crossing, then use linear interpolation to add an additional fractional
    component to the zero-crossing index (so our `crossings` indexes become float rather
    than int). This surprisingly makes a considerable difference in quantized frequencies,
    especially at lower divratios. However, this implementation isn't perfect, and it appears
    to add an oscillating uncertainty to time & frequency as we approach nyquist (or, perhaps,
    the zero-cross nyquist, which is something like samplerate / 2 / divratio).

    Returns updated crossings.
    """
    # TODO: investigate up-sampling the signal before zero-cross rather than interpolating after

    # This structured code is equivalent to the below one-liner. Perhaps some of these dtype
    # casts are unnecessary, but a few of them are critical for accuracy given our nano-second
    # scale.

    #interpolated_crossings = []
    #for i in crossings:
    #    a, b = np.int64(signal[i]), np.int64(signal[i+1])
    #    ra = b / np.float64(a - b)
    #    rb = a / np.float64(a - b)
    #    interpolated_crossings.append(i+rb)
    #crossings = np.array(interpolated_crossings, dtype=np.float64)

    # FIXME: This is slow, and should ideally be performed entirely within numpy
    # FIXME: noise_gate has significant influence (instead of i+1, interpolate to next non-zero value?)
    crossings = np.array([i+(np.int64(signal[i]) / np.float64(np.int64(signal[i]) - np.int64(signal[i+1]))) for i in crossings], dtype=np.float64)
    return crossings


@print_timing
def zero_cross(signal, samplerate, divratio, amplitudes=True, interpolation=False):
    """Produce (times in seconds, frequencies in Hz, and amplitudes) from calculated zero crossings"""
    # straight zero-cross without any samplerate interpolation
    log.debug('zero_cross2(..., %d, %d, amplitudes=%s, interpolation=%s)', samplerate, divratio, amplitudes, interpolation)
    divratio /= 2  # required so that our algorithm agrees with the Anabat ZCAIM algorithm

    crossings = np.where(np.diff(np.sign(signal)))[0][::divratio*2]  # indexes
    log.debug('Extracted %d crossings' % len(crossings))

    if amplitudes:
        amplitudes = np.asarray([chunk.mean() if chunk.any() else 0 for chunk in np.split(np.abs(signal), crossings)[:-1]])  # FIXME: slow (can we remain entirely in numpy here?)
        log.debug('Extracted %d amplitude values' % len(amplitudes))
    else:
        amplitudes = None

    if interpolation:
        crossings = interpolate(signal, crossings)

    times_s = crossings / samplerate
    intervals_s = np.ediff1d(times_s, to_end=0)  # TODO: benchmark, `diff` may be faster than `ediff1d` (but figure out if the 0 appended to end is necessary?)
    freqs_hz = 1.0 / intervals_s * divratio
    freqs_hz[np.isinf(freqs_hz)] = 0  # fix divide-by-zero
    # if not np.all(freqs_hz):
    #     bad_crossings = np.where(freqs_hz == 0.0)
    #     log.debug('Discarding %d bad crossings of 0Hz', len(bad_crossings))
    #     log.debug('  Before: %s', freqs_hz)
    #     freqs_hz = np.delete(freqs_hz, bad_crossings)
    #     times_s = np.delete(times_s, bad_crossings)
    #     amplitudes = np.delete(amplitudes, bad_crossings) if amplitudes is not None else None
    #     log.debug('   After: %s', freqs_hz)
    # else:
    #     log.debug('No bad crossings!')
    #     log.debug(freqs_hz)
    return times_s, freqs_hz, amplitudes


@print_timing
def hpf_zc(times_s, freqs_hz, amplitudes, cutoff_freq_hz):
    """Brickwall high-pass filter for zero-cross signals (simply discards everything < cutoff)"""
    hpf_mask = np.where(freqs_hz > cutoff_freq_hz)
    junk_count = len(freqs_hz) - np.count_nonzero(hpf_mask)
    log.debug('HPF throwing out %d dots of %d (%.1f%%)' % (junk_count, len(freqs_hz), junk_count/len(freqs_hz)*100))
    return times_s[hpf_mask], freqs_hz[hpf_mask], amplitudes[hpf_mask] if amplitudes is not None else None


@print_timing
def wav2zc(fname, divratio=8, hpfilter_khz=20, threshold_factor=1.0, interpolate=False, brickwall_hpf=True):
    """Convert a single .wav file to Anabat format.
    Produces (times in seconds, frequencies in Hz, amplitudes, metadata).

    signal -> HPF -> noise gate -> ZC -> brickwall HPF

    fname: input filename
    divratio: ZCAIM frequency division ratio (4, 8, 10, 16, or 32)
    hpfilter_khz: frequency in KHz of 6th-order high-pass butterworth filter; `None` or 0 to disable HPF
    threshold_factor: RMS multiplier for noise floor, applied after filter
    interpolate: use experimental dot interpolation or not (TODO: use upsampling instead)
    brickwall_hpf: whether we should throw out all dots which fall below our HPF threshold
    """

    log.debug('wav2zc(infile=%s, divratio=%d, hpf=%.1fKHz, threshold=%.1fxRMS, interpolate=%s)', fname, divratio, hpfilter_khz, threshold_factor, interpolate)

    # check params
    if divratio not in (4, 8, 10, 16, 32):
        raise Exception('Unsupported divratio: %s (Anabat132 supports 4, 8, 10, 16, 32)' % divratio)

    samplerate, signal = load_wav(fname)

    if hpfilter_khz:
        signal = highpassfilter(signal, samplerate, hpfilter_khz*1000)
    else:
        # HPF removes DC offset, so we manually remove it when not filtering
        log.debug('DC offset before: %.1f', np.sum(signal) / len(signal))
        signal = dc_offset(signal)
        log.debug('DC offset after:  %.1f', np.sum(signal) / len(signal))

    if threshold_factor:
        signal = noise_gate(signal, threshold_factor)  # TODO: is it OK that we're converting AC signal to DC here?

    times_s, freqs_hz, amplitudes = zero_cross(signal, samplerate, divratio, interpolation=interpolate)
    if brickwall_hpf and hpfilter_khz:
        times_s, freqs_hz, amplitudes = hpf_zc(times_s, freqs_hz, amplitudes, hpfilter_khz*1000)

    if len(freqs_hz) > 16384:  # Anabat file format max dots
        log.warn('File exceeds max dotcount (%d)! Consider raising DivRatio?', len(freqs_hz))

    min_ = np.amin(freqs_hz) if freqs_hz.any() else 0
    max_ = np.amax(freqs_hz) if freqs_hz.any() else 0
    log.debug('%s\tDots: %d\tMinF: %.1f\tMaxF: %.1f', os.path.basename(fname), len(freqs_hz), min_, max_)

    metadata = dict(divratio=divratio, timestamp=extract_timestamp(fname))
    return times_s, freqs_hz, amplitudes, metadata


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
