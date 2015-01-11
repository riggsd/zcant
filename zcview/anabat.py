import mmap
import struct
import contextlib
from glob import glob
from os.path import basename
from datetime import datetime

import numpy as np

from zcview import print_timing

import logging
log = logging.getLogger(__name__)

Byte = struct.Struct('< B')


ANABAT_129_HEAD_FMT = '< H x B 2x 8s 8s 40s 50s 16s 73s 80s'  # 0x0: data_info_pointer, file_type, tape, date, loc, species, spec, note1, note2
ANABAT_129_DATA_INFO_FMT = '< H H B B'  # 0x11a: data_pointer, res1, divratio, vres
ANABAT_132_ADDL_DATA_INFO_FMT = '< H B B B B B B H 6s 32s'  # 0x120: year, month, day, hour, minute, second, second_hundredths, microseconds, id_code, gps_data


def _s(s):
    """Strip whitespace and null bytes from string"""
    return s.strip('\00\t ')


@print_timing
def extract_anabat(fname):
    """Extract (times, frequencies, metadata) from Anabat sequence file"""
    with open(fname, 'rb') as f, contextlib.closing(mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)) as m:
        size = len(m)

        # parse header
        data_info_pointer, file_type, tape, date, loc, species, spec, note1, note2 = struct.unpack_from(ANABAT_129_HEAD_FMT, m)
        data_pointer, res1, divratio, vres = struct.unpack_from(ANABAT_129_DATA_INFO_FMT, m, data_info_pointer)
        species = [_s(species).split('(', 1)[0]] if '(' in species else [s.strip() for s in _s(species).split(',')]  # remove KPro junk
        metadata = dict(date=date, loc=_s(loc), species=species, spec=_s(spec), note1=_s(note1), note2=_s(note2), divratio=divratio)
        if file_type >= 132:
            year, month, day, hour, minute, second, second_hundredths, microseconds, id_code, gps_data = struct.unpack_from(ANABAT_132_ADDL_DATA_INFO_FMT, m, 0x120)
            timestamp = datetime(year, month, day, hour, minute, second, second_hundredths * 10000 + microseconds)
            metadata.update(dict(timestamp=timestamp, id=_s(id_code), gps=_s(gps_data)))
        log.debug('file_type: %d\tdata_info_pointer: 0x%3x\tdata_pointer: 0x%3x', file_type, data_info_pointer, data_pointer)
        log.debug(metadata)

        # parse actual sequence data
        i = data_pointer   # byte index as we scan through the file (data starts at 0x150 for v132, 0x120 for older files)
        intervals_us = np.empty(2**14, np.dtype('u4'))
        int_i = 0

        while i < size:
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
                # TODO: not yet supported

            else:
                raise Exception('Unknown byte %X at offset 0x%X' % (byte, i))

            i += 1

    intervals_us = intervals_us[:int_i]  # TODO: should we free unused memory?
    intervals_s = intervals_us * 1e-6
    times_s = np.cumsum(intervals_s)
    freqs_hz = 1 / intervals_s * (divratio / 2)
    freqs_hz[freqs_hz == np.inf] = 0  # fix divide-by-zero

    min_, max_ = min(freqs_hz) if any(freqs_hz) else 0, max(freqs_hz) if any(freqs_hz) else 0
    log.debug('%s\tDots: %d\tMinF: %.1f\tMaxF: %.1f', basename(fname), len(freqs_hz), min_/1000.0, max_/1000.0)
    
    return times_s, freqs_hz, metadata


if __name__ == '__main__':
    import os.path
    from matplotlib.pylab import *

    dirname = '/Users/driggs/bat_calls/NC/Boone/20141027/'

    for fname in glob(os.path.join(dirname, '*.*#'))[:5]:
        times, freqs, md = extract_anabat(fname)
        figure()
        title(os.path.basename(fname))
        ylabel('Frequency (Hz)')
        xlabel('Time (s)')
        grid(axis='y')
        ylim(15*1000, 70*1000)
        #xlim(1.0, 2.5)
        plot(times, freqs, ',')

    show()
