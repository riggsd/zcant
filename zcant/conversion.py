"""
Algorithm for conversion of .WAV audio to zero-crossing signal.

---------------
Myotisoft ZCANT
Copyright (C) 2012-2017 Myotisoft LLC, all rights reserved.
You may use, distribute, and modify this code under the terms of the MIT License.
"""


from __future__ import division

import io
import sys
import wave
import math
import struct
import os.path
import re
from datetime import datetime

import numpy as np
import scipy.signal

import logging
log = logging.getLogger(__name__)

from zcant import print_timing


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
def noise_gate_zc(times_s, freqs_hz, amplitudes, threshold_factor):
    """Discard low-amplitude portions of the zero-cross signal.
    threshold_factor: ratio of root-mean-square "noise floor" below which we drop
    """
    signal_rms = rms(amplitudes)
    threshold = threshold_factor * signal_rms
    log.debug('RMS: %.1f  threshold: %0.1f (%.1f x RMS)', signal_rms, threshold, threshold_factor)
    # ignore everything below threshold amplitude
    mask = amplitudes >= threshold
    return times_s[mask], freqs_hz[mask], amplitudes[mask]


# @print_timing
# def noise_gate(signal, threshold_factor):
#     """Discard low-amplitude portions of the signal.
#     threshold_factor: ratio of root-mean-square "noise floor" below which we drop
#     """
#     signal_rms = rms(signal)
#     threshold = threshold_factor * signal_rms
#     log.debug('RMS: %.1f  threshold: %0.1f (%.1f x RMS)', signal_rms, threshold, threshold_factor)
#     # ignore everything below threshold amplitude (and convert whole signal to DC!)
#     signal[signal < threshold] = 0
#     return signal


# def ms_to_samples(samplerate, ms):
#     """
#     Given a samplerate and a time span in milliseconds, calculate the number of samples required
#     to cover that time span
#     :param samplerate: samplerate in Hz
#     :param ms: time in milliseconds
#     :return: integer number of samples
#     """
#     return int(math.ceil(ms * samplerate / 1000.0))
#
# def pad_widths(N):
#     """Given a window size N, produce (front, rear) sizes require to pad back to original length"""
#     if not N:
#         raise ValueError(N)
#     N -= 1
#     return N // 2, N // 2 + N % 2
#
# def rolling_mean(signal, N):
#     """
#     Calculate the rolling mean of a signal, with window size N.
#     Front and rear of the output are padded with un-averaged signal values so that output size == input size
#     """
#     if not N:
#         raise ValueError(N)
#     elif N == 1:
#         return signal
#     cumsum = np.cumsum(np.insert(signal, 0, 0), dtype=np.float64)
#     mean = (cumsum[N:] - cumsum[:-N]) / N  # size len(signal) - N - 1
#     front, rear = pad_widths(N)
#     return np.append(np.insert(mean, 0, signal[:front]), signal[-rear:])
#
# @print_timing
# def noise_gate_ROLLING_MEAN(signal, samplerate, threshold_factor, window_size_ms=0.1):
#     """Discard low-amplitude portions of the signal.
#     threshold_factor: ratio of root-mean-square "noise floor" below which we drop
#     """
#     window_size = ms_to_samples(samplerate, window_size_ms)
#     signal_rms = rms(signal)
#     threshold = threshold_factor * signal_rms
#     log.debug('RMS: %.1f  threshold: %0.1f (%.1f x RMS)', signal_rms, threshold, threshold_factor)
#     mean_signal = rolling_mean(signal, window_size)
#     if len(mean_signal) != len(signal):
#         raise Exception('Rolling mean size is incorrect (mean %d vs original %d)' % (len(mean_signal), len(signal)))
#     output = signal.copy()
#     output[np.logical_and(mean_signal < threshold, output < threshold)] = 0  # NOTE: this converts signal to DC!
#     return output


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

    # interpolated_crossings = []
    # for i in crossings:
    #     a = np.int64(signal[i])
    #     b = np.int64(signal[i+1])
    #     ra = b / np.float64(a - b)
    #     rb = a / np.float64(a - b)
    #     interpolated_crossings.append(i + rb)
    # crossings = np.array(interpolated_crossings, dtype=np.float64)

    # FIXME: This is slow, and should ideally be performed entirely within numpy
    # FIXME: noise_gate has significant influence (instead of i+1, interpolate to next non-zero value?)
    crossings = np.array([i+(np.int64(signal[i]) / np.float64(np.int64(signal[i]) - np.int64(signal[i+1]))) for i in crossings], dtype=np.float64)
    return crossings


@print_timing
def zero_cross(signal, samplerate, divratio, amplitudes=True, interpolation=False):
    """Produce (times in seconds, frequencies in Hz, and amplitudes) from calculated zero crossings"""
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


# @print_timing
# def resample(samplerate, signal, target_samplerate=768000):
#     """Resample a full-spectrum signal to a higher samplerate - warning: too slow"""
#     if samplerate >= target_samplerate:
#         return samplerate, signal
#     new_length = 2 * len(signal)  #int(round(target_samplerate * len(signal) / samplerate))  # SLLOOOOOOOW.
#     signal = scipy.signal.resample(signal, new_length)
#     return target_samplerate, signal


@print_timing
def wav2zc(fname, divratio=8, hpfilter_khz=20, threshold_factor=1.0, interpolation=False, brickwall_hpf=True):
    """Convert a single .wav file to Anabat format.
    Produces (times in seconds, frequencies in Hz, amplitudes, metadata).

    Processing pipeline:
        signal -> HPF -> ZC w. interpolation -> brickwall HPF -> noise gate

    (We formerly applied noise gate to the full-spectrum signal, but that makes sample
    interpolation impossible(?). Zero-crossing without noise gate is slow, and slows down
    everything later in the pipeline... TODO: investigate other ways to clean up the signal
    prior to zero-crossing.)

    fname: input filename
    divratio: ZCAIM frequency division ratio (4, 8, 10, 16, or 32)
    hpfilter_khz: frequency in KHz of 6th-order high-pass butterworth filter; `None` or 0 to disable HPF
    threshold_factor: RMS multiplier for noise floor, applied after filter
    interpolate: use experimental dot interpolation or not (TODO: use upsampling instead)
    brickwall_hpf: whether we should throw out all dots which fall below our HPF threshold
    """

    log.debug('wav2zc(infile=%s, divratio=%d, hpf=%.1fKHz, threshold=%.1fxRMS, interpolate=%s)', fname, divratio, hpfilter_khz, threshold_factor, interpolation)
    do_hpfilter = hpfilter_khz is not None and not np.isclose(hpfilter_khz, 0.0)
    do_noise_gate = threshold_factor is not None and not np.isclose(threshold_factor, 0.0)
    if divratio not in (4, 8, 10, 16, 32):
        raise Exception('Unsupported divratio: %s (Anabat132 supports 4, 8, 10, 16, 32)' % divratio)

    samplerate, signal = load_wav(fname)

    if do_hpfilter:
        signal = highpassfilter(signal, samplerate, hpfilter_khz*1000)
    else:
        # HPF removes DC offset, so we manually remove it when not filtering
        log.debug('DC offset before: %.1f', np.sum(signal) / len(signal))
        signal = dc_offset(signal)
        log.debug('DC offset after:  %.1f', np.sum(signal) / len(signal))

    times_s, freqs_hz, amplitudes = zero_cross(signal, samplerate, divratio, interpolation=interpolation)
    if brickwall_hpf and do_hpfilter:
        times_s, freqs_hz, amplitudes = hpf_zc(times_s, freqs_hz, amplitudes, hpfilter_khz*1000)
    if do_noise_gate:
        log.debug('threshold_factor: %f  bool: %s  isclose: %s', threshold_factor, bool(threshold_factor), np.isclose(threshold_factor, 0.0))
        times_s, freqs_hz, amplitudes = noise_gate_zc(times_s, freqs_hz, amplitudes, threshold_factor)

    if len(freqs_hz) > 16384:  # Anabat file format max dots
        log.warn('File exceeds max dotcount (%d)! Consider raising DivRatio?', len(freqs_hz))

    min_ = np.amin(freqs_hz) if freqs_hz.any() else 0
    max_ = np.amax(freqs_hz) if freqs_hz.any() else 0
    log.debug('%s\tDots: %d\tMinF: %.1f\tMaxF: %.1f', os.path.basename(fname), len(freqs_hz), min_, max_)

    metadata = dict(divratio=divratio, timestamp=extract_timestamp(fname))
    return times_s, freqs_hz, amplitudes, metadata


TIMESTAMP_REGEX = re.compile(r'(\d{8}_\d{6})')

def extract_timestamp(fname):
    """Extract the timestamp from a file."""
    # For now we simply yank from the filename itself, no proper metadata support
    try:
        timestamp = TIMESTAMP_REGEX.search(fname).groups()[0]
        return datetime.strptime(timestamp, '%Y%m%d_%H%M%S')
    except:
        return None
