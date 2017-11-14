"""
Audio playback code.

---------------
Myotisoft ZCANT
Copyright (C) 2012-2017 Myotisoft LLC, all rights reserved.
You may use, distribute, and modify this code under the terms of the MIT License.
"""

import threading
import logging
from time import sleep
log = logging.getLogger(__name__)

from conversion import load_wav, load_windowed_wav

from scipy.io import wavfile

import sounddevice


__all__ = 'AudioThread', 'play_te', 'beep'


def beep():
    """Play an amazing beep sound."""
    # we opt out of our own `load_wav()` since this is low samplerate (no implied TE)
    samplerate, signal = wavfile.read('resources/beep.wav', mmap=True)
    AudioThread.play((samplerate, signal), te=None)


def play_te(fname, te=10, blocking=False):
    """Play a time-expanded version of the specified .WAV file or (samplerate, signal) .WAV data"""
    # TODO: Resample unsupported samplerate audio using https://github.com/bmcfee/resampy
    log.debug('play_te(%s, TE=%sX)', fname, te)
    if type(fname) == tuple:
        samplerate, signal = fname
    else:
        samplerate, signal = load_wav(fname)

    if te:
        samplerate //= te

    sounddevice.play(signal, samplerate, blocking=blocking)


class AudioThread(threading.Thread):
    """Stoppable asynchronous audio playback thread."""

    def __init__(self, fname, te=10):
        """Create a thread which plays the specified filename (or signal) with time-expansion"""
        threading.Thread.__init__(self, name='AudioThread')
        self.fname = fname
        self.te = te
        
        self.stop_requested = False
        self.stream = None
        self.daemon = True  # don't hang if program ends while playing

    @staticmethod
    def play(fname, te=10):
        """Convenience function which creates, starts playing, and returns a handle to the thread"""
        t = AudioThread(fname, te)
        t.start()
        return t

    @staticmethod
    def play_windowed(fname, te, start, duration):
        samplerate, signal = load_windowed_wav(fname, start, duration)
        return AudioThread.play((samplerate, signal), te)

    def run(self):
        # thread main
        play_te(self.fname, self.te, blocking=False)
        self.stream = sounddevice.get_stream()
        while self.stream.active:
            # poll because the underlying portaudio c-library segfaults on multithreaded access
            sleep(0.05)
            if self.stop_requested:
                sounddevice.stop()
                return
        
    def is_playing(self):
        """Check to see if this thread is still playing or if it is dead"""
        try:
            return self.stream is not None and self.stream.active
        except sounddevice.PortAudioError, e:
            return False

    def wait(self):
        """Turn a non-blocking call to `play_te()` into a blocking call"""
        return sounddevice.wait()

    def stop(self):
        """Stop audio playback"""
        self.stop_requested = True


def device_test():
    """Print some diagnostics about the underlying portaudio library and host audio support"""
    rates = [192, 250, 256, 300, 384, 441, 480, 500, 750, 768]

    def test_rates(rates):
        for r in rates:
            try:
                sounddevice.check_input_settings(samplerate=int(r*1000))
                print '\t%.1f kHz OK' % r
            except sounddevice.PortAudioError:
                print '\t%.1f kHz not supported!' % r

    print 'sounddevice ' + sounddevice.__version__
    print sounddevice.get_portaudio_version()[1]
    print sounddevice.query_devices()

    print '\n10x Time Expansion:'
    test_rates([r/10.0 for r in rates])
    print '\nRealtime:'
    test_rates(rates)


if __name__ == '__main__':
    # python -m zcant.audio
    device_test()

    # print 'Press CTRL-C to end time-expansion playback.'
    #
    # for te in 4, 8, 10, 12, 16, 20:
    #
    #     try:
    #         a = AudioThread.play('test.wav', te)
    #         while a.is_playing():
    #             pass
    #     except KeyboardInterrupt:
    #         a.stop()
    #         import time; time.sleep(0.01)
