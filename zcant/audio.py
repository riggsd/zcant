"""
Audio playback code.

---------------
Myotisoft ZCANT
Copyright (C) 2012-2017 Myotisoft LLC, all rights reserved.
You may use, distribute, and modify this code under the terms of the MIT License.
"""

import threading
from sys import stdout

from conversion import load_wav, highpassfilter

#import scipy.signal

import sounddevice
#print sounddevice.get_portaudio_version()


__all__ = 'AudioThread', 'play_te', 'beep'


def beep():
    """Play an amazing beep sound."""
    stdout.write('\a')
    stdout.flush()


def play_te(fname, te=10, blocking=False):
    """Play a time-expanded version of the specified .WAV file or (samplerate, signal) .WAV data"""
    print 'play_te(%s, TE=%dX)' % (fname, te)
    if type(fname) == tuple:
        samplerate, signal = fname
    else:
        samplerate, signal = load_wav(fname)

    samplerate //= te

    #if samplerate in (441000, 480000):  # unsupported high samplerates... oof!
    #    samplerate //= 10
    #    #signal = scipy.signal.decimate(signal, 10, ftype='fir', zero_phase=True)
    #    #signal = scipy.signal.resample(signal, len(signal) // 10, window='hamming')
    #    # UGH, both these options are terrible for audio. Look into: https://github.com/bmcfee/resampy

    sounddevice.play(signal, samplerate, blocking=blocking)


class AudioThread(threading.Thread):
    """Stoppable audio playback thread."""

    def __init__(self, fname, te=10):
        """Create a thread which plays the specified filename (or signal) with time-expansion"""
        threading.Thread.__init__(self, name='AudioThread')
        self.fname = fname
        self.te = te

    @staticmethod
    def play(fname, te=10):
        """Convenience function which creates, starts playing, and returns a handle to the thread"""
        t = AudioThread(fname, te)
        t.start()
        return t

    def run(self):
        play_te(self.fname, self.te, blocking=True)

    def is_playing(self):
        """Check to see if this thread is still playing or if it is dead"""
        return self.is_alive()

    def wait(self):
        """Turn a non-blocking call to `play_te()` into a blocking call"""
        return sounddevice.wait()

    def stop(self):
        """Stop audio playback"""
        if self.is_alive():
            sounddevice.stop()


if __name__ == '__main__':
    print 'Press CTRL-C to end time-expansion playback.'

    for te in 4, 8, 10, 12, 16, 20:

        try:
            a = AudioThread.play('test.wav', te)
            while a.is_playing():
                pass
        except KeyboardInterrupt:
            a.stop()
            import time; time.sleep(0.01)
