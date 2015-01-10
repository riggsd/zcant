import mmap
import struct
import contextlib
from glob import glob
from os.path import basename
from datetime import datetime

import logging
log = logging.getLogger(__name__)

Byte = struct.Struct('< B')


ANABAT_129_HEAD_FMT = '< H x B 2x 8s 8s 40s 50s 16s 73s 80s'  # 0x0: data_info_pointer, file_type, tape, date, loc, species, spec, note1, note2
ANABAT_129_DATA_INFO_FMT = '< H H B B'  # 0x11a: data_pointer, res1, divratio, vres
ANABAT_132_ADDL_DATA_INFO_FMT = '< H B B B B B B H 6s 32s'  # 0x120: year, month, day, hour, minute, second, second_hundredths, microseconds, id_code, gps_data


def _s(s):
    """Strip whitespace and null bytes from string"""
    return s.strip('\00\t ')


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
        intervals = []
        freqs = []  # collection of parsed frequency values
        times = []  # collection of microsecond time values from start of file (if freq is Y axis, then time is X axis)     

        while i < size: 
            byte = Byte.unpack_from(m, i)[0]

            if byte <= 0x7F:
                # Single byte is a 7-bit signed two's complement offset from previous interval
                offset = byte if byte < 2**6 else byte - 2**7  # clever two's complement unroll
                if intervals:
                    intervals.append(intervals[-1] + offset)
                else:
                    log.warning('Sequence file starts with a one-byte interval diff! Skipping byte %x', byte)
                    #intervals.append(offset)  # ?!

            elif 0x80 <= byte <= 0x9F:
                # time interval is contained in 13 bits, upper 5 from the remainder of this byte, lower 8 bits from the next byte
                accumulator = (byte & 0b00011111) << 8
                i += 1
                accumulator |= Byte.unpack_from(m, i)[0]
                intervals.append(accumulator)

            elif 0xA0 <= byte <= 0xBF:
                # interval is contained in 21 bits, upper 5 from the remainder of this byte, next 8 from the next byte and the lower 8 from the byte after that
                accumulator = (byte & 0b00011111) << 16
                i += 1
                accumulator |= Byte.unpack_from(m, i)[0] << 8
                i += 1
                accumulator |= Byte.unpack_from(m, i)[0]
                intervals.append(accumulator)

            elif 0xC0 <= byte <= 0xDF:
                # interval is contained in 29 bits, the upper 5 from the remainder of this byte, the next 8 from the following byte etc.
                accumulator = (byte & 0b00011111) << 24
                i += 1
                accumulator |= Byte.unpack_from(m, i)[0] << 16
                i += 1
                accumulator |= Byte.unpack_from(m, i)[0] << 8
                i += 1
                accumulator |= Byte.unpack_from(m, i)[0]
                intervals.append(accumulator)

            elif 0xE0 <= byte <= 0xFF:
                # status byte which applies to the next n dots
                status = byte & 0b00011111
                i += 1
                dotcount = Byte.unpack_from(m, i)[0]
                # TODO: not yet supported

            else:
                min_, max_ = min(freqs) if any(freqs) else 0, max(freqs) if any(freqs) else 0
                log.warning('%s\tDots: %d\t\tMinF: %d\t\tMaxF: %d', basename(fname), len(freqs), min_, max_)
                raise Exception('Unknown byte %X' % byte)

            #times.append(times[-1] + (intervals[-1] * 1.0e-6) if times else 0.0)
            i += 1

    freqs = [divratio * 0.5 / (i * 1.0e-6) for i in intervals if i]
    times = []
    for i, interval in enumerate(intervals):
        times.append(times[-1] + (interval * 1.0e-6) if i != 0 else 0.0)

    min_, max_ = min(freqs) if any(freqs) else 0, max(freqs) if any(freqs) else 0
    log.debug('%s\tDots: %d\tMinF: %d\tMaxF: %d', basename(fname), len(freqs), min_, max_)
    
    return times, freqs, metadata


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
