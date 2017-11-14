"""
Module for reading/writing the Anabat file format, as well as general zero-crossing routines.

---------------
Myotisoft ZCANT
Copyright (C) 2012-2017 Myotisoft LLC, all rights reserved.
You may use, distribute, and modify this code under the terms of the MIT License.
"""

import io
import mmap
import struct
import unicodedata
import contextlib
from os.path import basename
from datetime import datetime
from collections import OrderedDict

import numpy as np
from numpy.ma import masked_array

from guano import GuanoFile, base64decode, base64encode

from zcant import print_timing

import logging
log = logging.getLogger(__name__)


Byte = struct.Struct('< B')


ANABAT_129_HEAD_FMT = '< H x B 2x 8s 8s 40s 50s 16s 73s 80s'  # 0x0: data_info_pointer, file_type, tape, date, loc, species, spec, note1, note2
ANABAT_129_DATA_INFO_FMT = '< H H B B'  # 0x11a: data_pointer, res1, divratio, vres
ANABAT_132_ADDL_DATA_INFO_FMT = '< H B B B B B B H 6s 32s'  # 0x120: year, month, day, hour, minute, second, second_hundredths, microseconds, id_code, gps_data

GuanoFile.register('ZCANT', 'Amplitudes',
                   lambda b64data: np.frombuffer(base64decode(b64data)),
                   lambda data: base64encode(data.tobytes()))


class DotStatus:
    """Enumeration of dot status types"""
    OUT_OF_RANGE = 0
    OFF    = 1
    NORMAL = 2
    MAIN   = 3


def _s(s):
    """Strip whitespace and null bytes from string"""
    return s.strip('\00\t ')


@print_timing
def hpf_zc(times_s, freqs_hz, amplitudes, cutoff_freq_hz):
    if not cutoff_freq_hz or len(freqs_hz) == 0:
        return times_s, freqs_hz, amplitudes
    hpf_mask = np.where(freqs_hz > cutoff_freq_hz)
    junk_count = len(freqs_hz) - np.count_nonzero(hpf_mask)
    log.debug('Throwing out %d dots of %d (%.1f%%)', junk_count, len(freqs_hz), float(junk_count)/len(freqs_hz)*100)
    return times_s[hpf_mask], freqs_hz[hpf_mask], amplitudes[hpf_mask] if amplitudes is not None else None


@print_timing
def extract_anabat(fname, hpfilter_khz=8.0, **kwargs):
    """Extract (times, frequencies, amplitudes, metadata) from Anabat sequence file"""
    amplitudes = None
    with open(fname, 'rb') as f, contextlib.closing(mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)) as m:
        size = len(m)

        # parse header
        data_info_pointer, file_type, tape, date, loc, species, spec, note1, note2 = struct.unpack_from(ANABAT_129_HEAD_FMT, m)
        data_pointer, res1, divratio, vres = struct.unpack_from(ANABAT_129_DATA_INFO_FMT, m, data_info_pointer)
        species = [_s(species).split('(', 1)[0]] if '(' in species else [s.strip() for s in _s(species).split(',')]  # remove KPro junk
        metadata = dict(date=date, loc=_s(loc), species=species, spec=_s(spec), note1=_s(note1), note2=_s(note2), divratio=divratio)
        if file_type >= 132:
            year, month, day, hour, minute, second, second_hundredths, microseconds, id_code, gps_data = struct.unpack_from(ANABAT_132_ADDL_DATA_INFO_FMT, m, 0x120)
            try:
                timestamp = datetime(year, month, day, hour, minute, second, second_hundredths * 10000 + microseconds)
            except ValueError as e:
                log.exception('Failed extracting timestamp')
                timestamp = None
            metadata.update(dict(timestamp=timestamp, id=_s(id_code), gps=_s(gps_data)))
            if data_pointer - 0x150 > 12:  # and m[pos:pos+5] == 'GUANO':
                try:
                    guano = GuanoFile.from_string(m[0x150:data_pointer])
                    log.debug(guano.to_string())
                    amplitudes = guano.get('ZCANT|Amplitudes', None)
                except:
                    log.exception('Failed parsing GUANO metadata block')
            else:
                log.debug('No GUANO metadata found')
        log.debug('file_type: %d\tdata_info_pointer: 0x%3x\tdata_pointer: 0x%3x', file_type, data_info_pointer, data_pointer)
        log.debug(metadata)

        # parse actual sequence data
        i = data_pointer   # byte index as we scan through the file (data starts at 0x150 for v132, 0x120 for older files)
        intervals_us = np.empty(2**14, np.dtype('u4'))
        offdots = OrderedDict()  # dot index -> number of subsequent dots
        int_i = 0  # interval index

        while i < size:
            
            if int_i >= len(intervals_us):
                # Anabat files were formerly capped at 16384 dots, but may now be larger; grow
                intervals_us = np.concatenate((intervals_us, np.empty(2**14, np.dtype('u4'))))

            byte = Byte.unpack_from(m, i)[0]

            if byte <= 0x7F:
                # Single byte is a 7-bit signed two's complement offset from previous interval
                offset = byte if byte < 2**6 else byte - 2**7  # clever two's complement unroll
                if int_i > 0:
                    intervals_us[int_i] = intervals_us[int_i-1] + offset
                    int_i += 1
                else:
                    log.warning('Sequence file starts with a one-byte interval diff! Skipping byte %x', byte)
                    #intervals.append(offset)  # ?!

            elif 0x80 <= byte <= 0x9F:
                # time interval is contained in 13 bits, upper 5 from the remainder of this byte, lower 8 bits from the next byte
                accumulator = (byte & 0b00011111) << 8
                i += 1
                accumulator |= Byte.unpack_from(m, i)[0]
                intervals_us[int_i] = accumulator
                int_i += 1

            elif 0xA0 <= byte <= 0xBF:
                # interval is contained in 21 bits, upper 5 from the remainder of this byte, next 8 from the next byte and the lower 8 from the byte after that
                accumulator = (byte & 0b00011111) << 16
                i += 1
                accumulator |= Byte.unpack_from(m, i)[0] << 8
                i += 1
                accumulator |= Byte.unpack_from(m, i)[0]
                intervals_us[int_i] = accumulator
                int_i += 1

            elif 0xC0 <= byte <= 0xDF:
                # interval is contained in 29 bits, the upper 5 from the remainder of this byte, the next 8 from the following byte etc.
                accumulator = (byte & 0b00011111) << 24
                i += 1
                accumulator |= Byte.unpack_from(m, i)[0] << 16
                i += 1
                accumulator |= Byte.unpack_from(m, i)[0] << 8
                i += 1
                accumulator |= Byte.unpack_from(m, i)[0]
                intervals_us[int_i] = accumulator
                int_i += 1

            elif 0xE0 <= byte <= 0xFF:
                # status byte which applies to the next n dots
                status = byte & 0b00011111
                i += 1
                dotcount = Byte.unpack_from(m, i)[0]
                if status == DotStatus.OFF:
                    offdots[int_i] = dotcount
                else:
                    log.debug('UNSUPPORTED: Status %X for %d dots at dot %d (file offset 0x%X)', status, dotcount, int_i, i)

            else:
                raise Exception('Unknown byte %X at offset 0x%X' % (byte, i))

            i += 1

    intervals_us = intervals_us[:int_i]  # TODO: should we free unused memory?

    intervals_s = intervals_us * 1e-6
    times_s = np.cumsum(intervals_s)
    freqs_hz = 1 / intervals_s * (divratio / 2)
    freqs_hz[freqs_hz == np.inf] = 0  # TODO: fix divide-by-zero

    if offdots:
        n_offdots = sum(offdots.values())
        log.debug('Throwing out %d off-dots of %d (%.1f%%)', n_offdots, len(times_s), float(n_offdots)/len(times_s)*100)
        off_mask = np.zeros(len(intervals_us), dtype=bool)
        for int_i, dotcount in offdots.items():
            off_mask[int_i:int_i+dotcount] = True
        times_s = masked_array(times_s, mask=off_mask).compressed()
        freqs_hz = masked_array(freqs_hz, mask=off_mask).compressed()

    min_, max_ = min(freqs_hz) if any(freqs_hz) else 0, max(freqs_hz) if any(freqs_hz) else 0
    log.debug('%s\tDots: %d\tMinF: %.1f\tMaxF: %.1f', basename(fname), len(freqs_hz), min_/1000.0, max_/1000.0)

    times_s, freqs_hz, amplitudes = hpf_zc(times_s, freqs_hz, amplitudes, hpfilter_khz*1000)

    return times_s, freqs_hz, amplitudes, metadata


def anabat_filename(timestamp):
    """Convert python datetime to anabat-style 8.3 filename, eg 'M7122036.45#', or None if not possible"""
    if timestamp.year < 1990:
        return None
    year = str(timestamp.year - 1990) if timestamp.year < 2000 else chr(timestamp.year - 2000 + ord('A'))
    month = hex(timestamp.month)[2].upper()
    return '%s%s%02d%02d%02d.%02d#' % (year, month, timestamp.day, timestamp.hour, timestamp.minute, timestamp.second)


def _pad(s, length, pad_chr=' '):
    """Pad or truncate a string to specified length, mangling unicode down to str in the process"""
    if not s:
        return length * pad_chr
    if type(s) == unicode:
        s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore')
    return s[:length] + (length-len(s))*pad_chr


def _get_bytes(val, count):
    """Get a specified number of bytes from a numeric value.
    n = 0x345678
    get_bytes(n, 4) -> [0x78, 0x56, 0x34, 0x0]
    """
    return [val >> i*8 & 0xff for i in range(count)]


class AnabatFileWriter(object):
    """Interface for writing an Anabat file (v132).

    Does NOT support GPS, altitude, point status (offdots, maindots), out-of-range points.

    with AnabatWriter(outfname) as out:
        out.write_header(timestamp, 8, species='Mylu', note='line 1', note1='line 2')
        out.write_intervals(sequence_of_intervals)
    """

    def __init__(self, fname):
        self.fname = fname
        self._f = io.open(fname, 'wb', buffering=True)

        self.byte_count = 0      # current file size in bytes, including header
        self.interval_count = 0  # current count of interval values
        self.length_us = 0       # current length in microseconds
        self.data_pointer = 0x150

        self._prev_interval = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__, self.fname)

    def write_header(self, timestamp, divratio, tape=None, loc=None, species=None, spec=None, note1=None, note2=None, id_code=None, res1=25000, vres=0x52, guano=None):
        """Write the Anabat 132 metadata header. This MUST be called before `write_intervals()`."""
        date = timestamp.strftime('%Y%m%d') if timestamp else '        '
        self._write_start()
        self._write_text_header(tape, date, loc, species, spec, note1, note2)
        if guano:
            guano = guano.serialize()
        data_pointer = 0x150 if not guano else 0x150 + len(guano)
        self._write_data_information_table(res1, divratio, vres, data_pointer)
        self._write_timestamp_etc(timestamp, id_code)
        self._write_guano(guano)

    def _write_start(self):
        self._f.write( struct.pack('< H x B 2x', 0x011a, 132) )  # pointer to data info table (0x011a), file structure version (Anabat 132)
        self.byte_count = 6

    def _write_text_header(self, tape=None, date=None, loc=None, species=None, spec=None, note=None, note1=None):

        def _write_str(s, length):
            self._f.write( struct.pack('< %ds' % length, _pad(s, length)) )

        _write_str(tape, 8)
        _write_str(date, 8)
        _write_str(loc, 40)
        _write_str(species, 50)
        _write_str(spec, 16)
        _write_str(note, 73)
        _write_str(note1, 80)
        self._f.write( struct.pack('x') )
        self.byte_count += 275

    def _write_data_information_table(self, res1=25000, divratio=16, vres=0x52, data_pointer=0x150):
        self._f.write( struct.pack('< H H B B', data_pointer, res1, divratio, vres))
        self.byte_count += 6

    def _write_timestamp_etc(self, timestamp, id_code=None):
        if timestamp:
            self._f.write( struct.pack('< H B B B B B B H', timestamp.year, timestamp.month, timestamp.day, timestamp.hour, timestamp.minute, timestamp.second, timestamp.microsecond / 10000, timestamp.microsecond % 10000) )
        else:
            self._f.write( struct.pack('< H B B B B B B H', 0, 0, 0, 0, 0, 0, 0, 0) )
        self._f.write( struct.pack('< 6s 32s', _pad(id_code, 6), '') )  # TODO: GPS position
        self.byte_count += 48

    def _write_guano(self, guano):
        if not guano:
            return
        self._f.write(guano)
        self.byte_count += len(guano)

    def write_intervals(self, intervals):
        """Write a sequence of transition intervals. You may call this multiple times."""
        for interval in intervals:
            self.interval_count += 1
            self.length_us += interval

            if self._prev_interval is not None:
                diff = interval - self._prev_interval

            if self._prev_interval is not None and abs(diff) < 64:
                # we can store this interval in one byte, as the offset from previous interval
                if diff >= 0:
                    self._f.write( struct.pack('< B', diff) )
                else:
                    # negative number is 7-bit twos-compliment, jeesh!
                    byte = ~ (abs(diff) - 1) & 0x7f  # 0b01111111 to ensure bit 7 is zero
                    self._f.write( struct.pack('< B', byte) )
                self.byte_count += 1

            elif interval < 0x2000:
                # interval represented as 13 bits in a two-byte chunk
                bytes = _get_bytes(interval, 2)
                self._f.write( struct.pack('< 2B', 0x80 | bytes[1], bytes[0]) )  # set 0b10100000 on highest byte
                self.byte_count += 2

            elif interval < 0x200000:
                # interval represented as 21 bits in a three-byte chunk
                bytes = _get_bytes(interval, 3)
                self._f.write( struct.pack('< 3B', 0xa0 | bytes[2], bytes[1], bytes[0]) )  # set 0b110xxxxx on highest byte
                self.byte_count += 3

            elif interval < 0x20000000:
                # interval represented as 29 bits in a four-byte chunk
                bytes = _get_bytes(interval, 4)
                self._f.write( struct.pack('< 4B', 0xc0 | bytes[3], bytes[2], bytes[1], bytes[0]) )  # set 0b11000000 on highest byte
                self.byte_count += 4

            else:
                log.warn('Interval %s out of range, unable to encode!', interval)

            self._prev_interval = interval

            # TODO: issue warning if interval count, byte length, or time exceeds max allowed

    def close(self):
        """Close the outfile and free resources."""
        self._f.close()
