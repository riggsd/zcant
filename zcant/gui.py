"""
ZCANT main GUI code.

---------------
Myotisoft ZCANT
Copyright (C) 2012-2017 Myotisoft LLC, all rights reserved.
You may use, distribute, and modify this code under the terms of the MIT License.
"""


from __future__ import division

import os
import os.path
import json
import webbrowser
from bisect import bisect
from fnmatch import fnmatch

import wx

import numpy as np

from zcant import __version__, print_timing
from zcant.audio import AudioThread, beep
from zcant.core import MainThread, AnabatFileWriteThread
from zcant.system import launch_external, browse_external
from zcant.plot import ZeroCrossPlotPanel
from zcant.wx_custom import HpfToolbarSpinner, ThresholdToolbarSlider, EVT_FLOATSPIN

import logging
log = logging.getLogger(__name__)


CONF_FNAME = os.path.expanduser('~/.myotisoft/zcant.ini')

CMAPS = ['gnuplot', 'jet', 'plasma', 'viridis', 'brg']


def title_from_path(path):
    """Create a friendly plot title given a file path"""
    root, fname = os.path.split(path)
    root, parent = os.path.split(root)
    root, gparent = os.path.split(root)
    if gparent:
        title = '%s %s %s %s %s' % (gparent, os.sep, parent, os.sep, fname)
    elif parent:
        title = '%s %s %s' % (parent, os.sep, fname)
    else:
        title = fname
    return title.replace('_', ' ')


class ZcantMainFrame(wx.Frame, wx.FileDropTarget):
    """This is the main ZCANT GUI window"""

    WAV_THRESHOLD_DELTA = 0.25  # RMS ratio
    HPF_DELTA = 2.5             # kHz
    FREQ_MINS = [5, 10, 15, 20]           # kHz
    FREQ_MAXS = [80, 100, 125, 150, 200]  # kHz

    def __init__(self, parent, title='Myotisoft ZCANT '+__version__):
        wx.Frame.__init__(self, parent, title=title, size=(640,480))

        # Application State - set initial defaults, then read state from conf file
        self.dirname = ''
        self.filename = ''

        self.is_compressed = True
        self.is_linear_scale = True
        self.use_smoothed_slopes = True
        self.display_cursor = False
        self.display_pulse_markers = True
        self.cmap = 'gnuplot'
        self.freq_min, self.freq_max = 15, 100
        self.harmonics = {'0.5': False, '1': True, '2': False, '3': False}

        self.wav_threshold = 1.5
        self.wav_divratio = 16
        self.hpfilter = 17.5
        self.wav_interpolation = True
        self.autosave = False

        self.window_secs = None
        self.window_start = 0.0

        self.main_thread = None
        self.audio_thread = None

        self.read_conf()

        # Initialize and load...
        log.debug('Initializing GUI...')
        self.init_gui()
        log.debug('GUI initialized.')

        if self.dirname and self.filename:
            try:
                self.load_file(self.dirname, self.filename)
            except Exception:
                log.exception('Failed opening default file: %s', os.path.join(self.dirname, self.filename))
        else:
            log.debug('No valid dirname/filename; doing nothing.')

    def init_gui(self):
        self.plotpanel = None

        self.init_menu()

        self.init_toolbar()

        self.statusbar = self.CreateStatusBar()

        self.init_keybindings()

        # configure drag-and-drop
        wx.FileDropTarget.__init__(self)
        self.SetDropTarget(self)

    def init_menu(self):
        # Menu Bar
        menu_bar = wx.MenuBar()

        # -- File Menu
        file_menu = wx.Menu()
        open_item = file_menu.Append(wx.ID_OPEN, '&Open\tCtrl+O', ' Open a .WAV or zero-cross file')
        self.Bind(wx.EVT_MENU, self.on_open, open_item)
        save_item = file_menu.Append(wx.ID_SAVE, '&Save\tCtrl+S', ' Save the converted zero-cross file')
        self.Bind(wx.EVT_MENU, self.on_save_file, save_item)
        print_item = file_menu.Append(wx.ID_ANY, 'Save &Plot\tCtrl+P', ' Save a .PNG screenshot of the current plot')
        delete_item = file_menu.Append(wx.ID_DELETE, '&Delete\tDEL', ' Delete the current file')
        self.Bind(wx.EVT_MENU, self.on_file_delete, delete_item)
        delete_item = file_menu.Append(wx.ID_DELETE, '&Delete ZC\tShift+DEL', ' Delete just the converted zero-cross version of the current file')
        self.Bind(wx.EVT_MENU, self.on_file_delete, delete_item)
        browse_item = file_menu.Append(wx.ID_ANY, 'Browse to File', ' Browse to file using your OS file manager')
        self.Bind(wx.EVT_MENU, lambda e: browse_external(os.path.join(self.dirname, self.filename)), browse_item)
        about_item = file_menu.Append(wx.ID_ABOUT, '&About', ' Information about this program')
        self.Bind(wx.EVT_MENU, self.on_about, about_item)
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, 'E&xit', ' Terminate this program')
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        menu_bar.Append(file_menu, '&File')

        # -- View Menu
        view_menu = wx.Menu()
        zoom_in_item = view_menu.Append(wx.ID_ANY, 'Zoom In\t+', ' Zoom display in')
        self.Bind(wx.EVT_MENU, self.on_zoom_in, zoom_in_item)
        zoom_out_item = view_menu.Append(wx.ID_ANY, 'Zoom Out\t-', ' Zoom display out')
        self.Bind(wx.EVT_MENU, self.on_zoom_out, zoom_out_item)
        zoom_whole_item = view_menu.Append(wx.ID_ANY, 'Whole File\t0', ' Zoom display out to show the entire file')
        self.Bind(wx.EVT_MENU, self.on_zoom_off, zoom_whole_item)

        view_menu.AppendSeparator()
        compressed_item = view_menu.AppendRadioItem(wx.ID_ANY, 'Compressed View\tSpace', ' View file in compressed (dot-per-pixel) mode')
        self.Bind(wx.EVT_MENU, self.on_compressed_toggle, compressed_item)
        realtime_item = view_menu.AppendRadioItem(wx.ID_ANY, 'Realtime View', ' View file in realtime mode')
        self.Bind(wx.EVT_MENU, self.on_compressed_toggle, realtime_item)
        compressed_item.Check(self.is_compressed)
        realtime_item.Check(not self.is_compressed)

        view_menu.AppendSeparator()
        min_freq_menu = wx.Menu()
        for f in ZcantMainFrame.FREQ_MINS:
            item = min_freq_menu.AppendRadioItem(wx.ID_ANY, '%2d kHz' % f)
            item.Check(self.freq_min == f)
            self.Bind(wx.EVT_MENU, self.on_freq_min_change, item)
        view_menu.AppendSubMenu(min_freq_menu, 'Min Frequency', ' Change the minimum displayed frequency')
        max_freq_menu = wx.Menu()
        for f in ZcantMainFrame.FREQ_MAXS:
            item = max_freq_menu.AppendRadioItem(wx.ID_ANY, '%3d kHz' % f)
            item.Check(self.freq_max == f)
            self.Bind(wx.EVT_MENU, self.on_freq_max_change, item)
        view_menu.AppendSubMenu(max_freq_menu, 'Max Frequency', ' Change the maximum displayed frequency')

        view_menu.AppendSeparator()
        log_item = view_menu.AppendRadioItem(wx.ID_ANY, 'Log Scale\tL', ' Logarithmic frequency scale')
        self.Bind(wx.EVT_MENU, self.on_scale_toggle, log_item)
        linear_item = view_menu.AppendRadioItem(wx.ID_ANY, 'Linear Scale', ' Linear frequency scale')
        self.Bind(wx.EVT_MENU, self.on_scale_toggle, linear_item)
        log_item.Check(not self.is_linear_scale)
        linear_item.Check(self.is_linear_scale)

        view_menu.AppendSeparator()
        smooth_item = view_menu.AppendCheckItem(wx.ID_ANY, 'Smooth Slopes', 'Smooth out noisy slope values')
        self.Bind(wx.EVT_MENU, self.on_smooth_slope_toggle, smooth_item)
        smooth_item.Check(self.use_smoothed_slopes)

        view_menu.AppendSeparator()
        cursor_item = view_menu.AppendCheckItem(wx.ID_ANY, 'Display Cursor', 'Display horizontal and vertical cursors')
        self.Bind(wx.EVT_MENU, self.on_cursor_toggle, cursor_item)
        cursor_item.Check(self.display_cursor)

        view_menu.AppendSeparator()
        pulse_marker_item = view_menu.AppendCheckItem(wx.ID_ANY, 'Pulse Markers', 'Display vertical pulse markers in compressed view')
        self.Bind(wx.EVT_MENU, self.on_pulse_marker_toggle, pulse_marker_item)
        pulse_marker_item.Check(self.display_pulse_markers)

        view_menu.AppendSeparator()
        h05_item = view_menu.AppendCheckItem(wx.ID_ANY, '1/2 Harmonic', ' One-half harmonic')
        self.Bind(wx.EVT_MENU, lambda e: self.on_harmonic_toggle('0.5'), h05_item)
        h1_item =  view_menu.AppendCheckItem(wx.ID_ANY, 'Fundamental',  ' Fundamental frequency')
        h2_item =  view_menu.AppendCheckItem(wx.ID_ANY, '2nd Harmonic', ' 2nd harmonic')
        self.Bind(wx.EVT_MENU, lambda e: self.on_harmonic_toggle('2'), h2_item)
        h3_item =  view_menu.AppendCheckItem(wx.ID_ANY, '3nd Harmonic', ' 3rd harmonic')
        self.Bind(wx.EVT_MENU, lambda e: self.on_harmonic_toggle('3'), h3_item)
        menu_bar.Append(view_menu, '&View')

        # -- Conversion Menu
        convert_menu = wx.Menu()

        autosave_item = convert_menu.AppendCheckItem(wx.ID_ANY, 'Auto-Save', ' Automatically save converted .WAV files to Anabat format')
        autosave_item.Check(self.autosave)
        self.Bind(wx.EVT_MENU, self.on_autosave_toggle, autosave_item)

        convert_menu.AppendSeparator()
        div4_item = convert_menu.AppendRadioItem(wx.ID_ANY, 'Div 4', ' 1/4 frequency division ratio')
        div4_item.Check(self.wav_divratio == 4)
        self.Bind(wx.EVT_MENU, lambda e: self.on_divratio_select(4), div4_item)
        div8_item = convert_menu.AppendRadioItem(wx.ID_ANY, 'Div 8', ' 1/8 frequency division ratio')
        div8_item.Check(self.wav_divratio == 8)
        self.Bind(wx.EVT_MENU, lambda e: self.on_divratio_select(8), div8_item)
        div16_item = convert_menu.AppendRadioItem(wx.ID_ANY, 'Div 16', ' 1/16 frequency division ratio')
        div16_item.Check(self.wav_divratio == 16)
        self.Bind(wx.EVT_MENU, lambda e: self.on_divratio_select(16), div16_item)
        div32_item = convert_menu.AppendRadioItem(wx.ID_ANY, 'Div 32', ' 1/32 frequency division ratio')
        div32_item.Check(self.wav_divratio == 32)
        self.Bind(wx.EVT_MENU, lambda e: self.on_divratio_select(32), div32_item)

        convert_menu.AppendSeparator()
        interpolation_item = convert_menu.AppendCheckItem(wx.ID_ANY, 'Interpolate', ' Interpolate between .WAV samples')
        self.Bind(wx.EVT_MENU, self.on_interpolation_toggle, interpolation_item)
        interpolation_item.Check(self.wav_interpolation)

        menu_bar.Append(convert_menu, '&Conversion')

        # -- Help Menu
        help_menu = wx.Menu()
        keybindings_item = help_menu.Append(wx.ID_ANY, 'Keyboard Shortcuts', ' View list of keyboard shortcuts')
        self.Bind(wx.EVT_MENU, self.on_view_keybindings, keybindings_item)
        website_item = help_menu.Append(wx.ID_ANY, 'Myotisoft Website', ' Visit the Myotisoft website')
        self.Bind(wx.EVT_MENU, lambda e: webbrowser.open_new_tab('http://myotisoft.com'), website_item)
        menu_bar.Append(help_menu, '&Help')

        self.SetMenuBar(menu_bar)

    def init_toolbar(self):
        # Nav Toolbar
        tool_bar = self.CreateToolBar(wx.TB_TEXT)
        open_item = tool_bar.AddLabelTool(wx.ID_ANY, 'Open',
                                          wx.Bitmap('resources/icons/file-8x.png'),
                                          shortHelp='Open')
        self.Bind(wx.EVT_TOOL, self.on_open, open_item)

        tool_bar.AddSeparator()
        prev_dir = tool_bar.AddLabelTool(wx.ID_ANY, 'Prev Folder',
                                         wx.Bitmap('resources/icons/chevron-left-8x.png'),
                                         shortHelp='Prev folder',
                                         longHelp='Open the previous folder (or use the `{` key)')
        self.Bind(wx.EVT_TOOL, self.on_prev_dir, prev_dir)
        prev_file = tool_bar.AddLabelTool(wx.ID_ANY, 'Prev File',
                                          wx.Bitmap('resources/icons/caret-left-8x.png'),
                                          shortHelp='Prev file',
                                          longHelp='Open the previous file in this folder (or use `[` key)')
        self.Bind(wx.EVT_TOOL, self.on_prev_file, prev_file)
        next_file = tool_bar.AddLabelTool(wx.ID_ANY, 'Next File',
                                          wx.Bitmap('resources/icons/caret-right-8x.png'),
                                          shortHelp='Next file',
                                          longHelp='Open the next file in this folder (or use the `]` key)')
        self.Bind(wx.EVT_TOOL, self.on_next_file, next_file)
        next_dir = tool_bar.AddLabelTool(wx.ID_ANY, 'Next Folder',
                                         wx.Bitmap('resources/icons/chevron-right-8x.png'),
                                         shortHelp='Next folder',
                                         longHelp='Open the next folder (or use the `}` key)')
        self.Bind(wx.EVT_TOOL, self.on_next_dir, next_dir)

        tool_bar.AddSeparator()
        toggle_compressed = tool_bar.AddLabelTool(wx.ID_ANY, 'Compressed', wx.Bitmap(
            'resources/icons/audio-spectrum-8x.png'),
                                                  shortHelp='Toggle compressed',
                                                  longHelp='Toggle compressed view on/off (or use the `c` key)')
        self.Bind(wx.EVT_TOOL, self.on_compressed_toggle, toggle_compressed)

        tool_bar.AddSeparator()
        play_button = tool_bar.AddLabelTool(wx.ID_ANY, 'Play TE', wx.Bitmap(
            'resources/icons/volume-high-8x.png'),
                                            shortHelp='Play time-expanded audio',
                                            longHelp='Play (or stop playing) 10X time-expanded audio')
        self.Bind(wx.EVT_TOOL, self.on_audio_play_te, play_button)

        tool_bar.AddSeparator()

        self.threshold_slider = ThresholdToolbarSlider(tool_bar, self.wav_threshold, self.WAV_THRESHOLD_DELTA)
        self.Bind(wx.EVT_SCROLL_THUMBRELEASE, self.on_threshold_slider, self.threshold_slider)

        self.hpf_spinner = HpfToolbarSpinner(tool_bar, self.hpfilter, self.HPF_DELTA)
        self.Bind(EVT_FLOATSPIN, self.on_hpfilter_spinner, self.hpf_spinner)

        tool_bar.Realize()

    def init_keybindings(self):
        # Key Bindings
        # TODO: move all these IDs to global scope and reuse them in menubar
        prev_file_id, next_file_id, prev_dir_id, next_dir_id = wx.NewId(), wx.NewId(), wx.NewId(), wx.NewId()
        delete_file_id, delete_zc_file_id = wx.NewId(), wx.NewId()
        compressed_id, scale_id, cmap_id, cmap_back_id = wx.NewId(), wx.NewId(), wx.NewId(), wx.NewId()
        threshold_up_id, threshold_down_id, hpfilter_up_id, hpfilter_down_id = wx.NewId(), wx.NewId(), wx.NewId(), wx.NewId()
        win_forward_id, win_back_id, win_zoom_in, win_zoom_out, win_zoom_off = wx.NewId(), wx.NewId(), wx.NewId(), wx.NewId(), wx.NewId()
        save_file_id, save_image_id = wx.NewId(), wx.NewId()
        play_audio_te_id, play_audio_rt_id = wx.NewId(), wx.NewId()

        self.Bind(wx.EVT_MENU, self.on_prev_file, id=prev_file_id)
        self.Bind(wx.EVT_MENU, self.on_next_file, id=next_file_id)
        self.Bind(wx.EVT_MENU, self.on_prev_dir, id=prev_dir_id)
        self.Bind(wx.EVT_MENU, self.on_next_dir, id=next_dir_id)
        self.Bind(wx.EVT_MENU, self.on_file_delete, id=delete_file_id)
        self.Bind(wx.EVT_MENU, self.on_zc_file_delete, id=delete_zc_file_id)
        self.Bind(wx.EVT_MENU, self.on_compressed_toggle, id=compressed_id)
        self.Bind(wx.EVT_MENU, self.on_scale_toggle, id=scale_id)
        self.Bind(wx.EVT_MENU, self.on_cmap_switch, id=cmap_id)
        self.Bind(wx.EVT_MENU, self.on_cmap_back, id=cmap_back_id)
        self.Bind(wx.EVT_MENU, self.on_threshold_up, id=threshold_up_id)
        self.Bind(wx.EVT_MENU, self.on_threshold_down, id=threshold_down_id)
        self.Bind(wx.EVT_MENU, self.on_hpfilter_up, id=hpfilter_up_id)
        self.Bind(wx.EVT_MENU, self.on_hpfilter_down, id=hpfilter_down_id)
        self.Bind(wx.EVT_MENU, self.on_save_file, id=save_file_id)
        self.Bind(wx.EVT_MENU, self.on_save_image, id=save_image_id)
        self.Bind(wx.EVT_MENU, self.on_win_forward, id=win_forward_id)
        self.Bind(wx.EVT_MENU, self.on_win_back, id=win_back_id)
        self.Bind(wx.EVT_MENU, self.on_zoom_in, id=win_zoom_in)
        self.Bind(wx.EVT_MENU, self.on_zoom_out, id=win_zoom_out)
        self.Bind(wx.EVT_MENU, self.on_zoom_off, id=win_zoom_off)
        self.Bind(wx.EVT_MENU, self.on_audio_play_te, id=play_audio_te_id)
        self.Bind(wx.EVT_MENU, self.on_audio_play_rt, id=play_audio_rt_id)

        a_table = wx.AcceleratorTable([
            (wx.ACCEL_NORMAL, ord('['),  prev_file_id),
            (wx.ACCEL_NORMAL, wx.WXK_F3, prev_file_id),
            (wx.ACCEL_NORMAL, ord(']'),  next_file_id),
            (wx.ACCEL_NORMAL, wx.WXK_F4, next_file_id),

            (wx.ACCEL_SHIFT, ord('['), prev_dir_id),  # {
            (wx.ACCEL_SHIFT, ord(']'), next_dir_id),  # }

            (wx.ACCEL_NORMAL, wx.WXK_DELETE, delete_file_id),
            (wx.ACCEL_NORMAL, wx.WXK_BACK,   delete_file_id),  # pretend delete and backspace are the same keys!
            (wx.ACCEL_SHIFT,  wx.WXK_DELETE, delete_zc_file_id),
            (wx.ACCEL_SHIFT,  wx.WXK_BACK,   delete_zc_file_id),

            (wx.ACCEL_NORMAL, wx.WXK_SPACE, compressed_id),
            (wx.ACCEL_NORMAL, ord('l'), scale_id),

            (wx.ACCEL_NORMAL, ord('c'), cmap_id),
            (wx.ACCEL_SHIFT,  ord('c'), cmap_back_id),

            (wx.ACCEL_NORMAL, wx.WXK_UP,   threshold_up_id),
            (wx.ACCEL_NORMAL, wx.WXK_DOWN, threshold_down_id),

            (wx.ACCEL_SHIFT, wx.WXK_UP,   hpfilter_up_id),
            (wx.ACCEL_SHIFT, wx.WXK_DOWN, hpfilter_down_id),

            (wx.ACCEL_NORMAL, wx.WXK_RIGHT, win_forward_id),
            (wx.ACCEL_NORMAL, wx.WXK_LEFT,  win_back_id),
            (wx.ACCEL_SHIFT,  ord('='), win_zoom_in),   # +
            (wx.ACCEL_NORMAL, ord('='), win_zoom_in),
            (wx.ACCEL_SHIFT,  ord('-'), win_zoom_out),  # -
            (wx.ACCEL_NORMAL, ord('-'), win_zoom_out),
            (wx.ACCEL_NORMAL, ord('0'), win_zoom_off),

            (wx.ACCEL_CMD, ord('p'), save_image_id),
            (wx.ACCEL_CMD, ord('s'), save_file_id),

            (wx.ACCEL_NORMAL, ord('p'), play_audio_te_id),
            (wx.ACCEL_SHIFT,  ord('p'), play_audio_rt_id),
        ])
        self.SetAcceleratorTable(a_table)

    def on_save_image(self, event):
        if not self.plotpanel or not self.filename or not self.dirname:
            return
        imagename = os.path.splitext(os.path.join(self.dirname, self.filename))[0] + '.png'
        log.debug('Saving image: %s', imagename)
        try:
            self.plotpanel.figure.savefig(imagename)
        except Exception:
            log.exception('Failed saving image: %s', imagename)

    def on_autosave_toggle(self, event):
        log.debug('Turning %s auto-save mode', 'off' if self.autosave else 'on')
        self.autosave = not self.autosave

    def get_zc_outdir(self):
        return os.path.join(self.dirname, '_ZCANT_Converted')

    def get_zc_outfname(self):
        return self.filename[:-4]+'.zc'

    def get_zc_outfpath(self):
        return os.path.join(self.get_zc_outdir(), self.get_zc_outfname())

    def get_delete_outdir(self):
        return os.path.join(self.dirname, 'Deleted Files')

    def _ensure_dir(self, dirpath):
        if not os.path.exists(dirpath):
            os.makedirs(dirpath)
        return dirpath

    def ensure_delete_outdir(self):
        return self._ensure_dir(self.get_delete_outdir())

    def ensure_zc_outdir(self):
        return self._ensure_dir(self.get_zc_outdir())

    @print_timing
    def on_save_file(self, event):
        # For now, we will only save a converted .WAV as Anabat file
        if not self.filename.lower().endswith('.wav'):
            return
        outfile = self.get_zc_outfpath()
        AnabatFileWriteThread(self.zc, outfile, self.wav_divratio)

    def on_file_delete(self, event):
        log.debug('Delete file')
        currentfile = os.path.join(self.dirname, self.filename)
        if not os.path.exists(currentfile):
            return  # we've deleted ourselves into a hole
        self.on_zc_file_delete(None)
        dest = self.ensure_delete_outdir()
        renamed = os.path.join(dest, os.path.basename(self.filename))
        log.debug('Moving file %s -> %s', currentfile, renamed)
        os.rename(currentfile, renamed)
        self.on_next_file(None)

    def on_zc_file_delete(self, event):
        log.debug('Delete ZC file')
        zcfile = self.get_zc_outfpath()
        if not os.path.exists(zcfile):
            return
        dest = self.ensure_delete_outdir()
        renamed = os.path.join(dest, os.path.basename(zcfile))
        log.debug('Moving file %s -> %s', zcfile, renamed)
        os.rename(zcfile, renamed)

    def on_audio_play_te(self, event):
        return self._on_audio_play(10)

    def on_audio_play_rt(self, event):
        return self._on_audio_play(1)

    def _on_audio_play(self, te):
        if self.audio_thread is not None and self.audio_thread.is_playing():
            self.audio_thread.stop()
        else:
            if not self.filename.lower().endswith('.wav'):
                return
            filename = os.path.join(self.dirname, self.filename)
            if self.window_secs:
                self.audio_thread = AudioThread.play_windowed(filename, te, self.window_start, self.window_secs)
            else:
                self.audio_thread = AudioThread.play(filename, te)

    def on_about(self, event):
        log.debug('about: %s', event)
        dlg = wx.MessageDialog(self, 'A boring Zero-Cross Viewer!', 'About ZCANT', wx.OK)
        dlg.ShowModal()
        dlg.Destroy()

    def on_view_keybindings(self, event):
        log.debug('keybindings: %s', event)
        fname = os.path.normpath('resources/keybindings.pdf')
        # Ugh, pkg_resources API doesn't work with py2app, so we try a few methods to find file
        if os.path.exists(fname):
            launch_external(fname)
        else:
            from pkg_resources import resource_exists, resource_filename
            if resource_exists('zcant', fname):
                launch_external(resource_filename(fname))
            else:
                log.debug('Unable to locate file %s !', fname)

    def on_exit(self, event):
        log.debug('exit: %s', event)
        self.Close(True)

    def on_open(self, event):
        log.debug('open: %s', event)
        dlg = wx.FileDialog(self, 'Choose a file', self.dirname, '', 'Anabat files|*.*|Anabat files|*.zc|Wave files|*.wav', wx.OPEN)
        if dlg.ShowModal() == wx.ID_OK:
            filename = dlg.GetFilename()
            dirname = dlg.GetDirectory()
            log.debug('open: %s', os.path.join(dirname, filename))
            self.load_file(dirname, filename)
            self.save_conf()
        dlg.Destroy()

    def OnDropFiles(self, x, y, filenames):
        """File drag-and-drop handler"""
        log.debug('OnDropFiles: %s, %s, %s', x, y, filenames)
        filename = filenames[0]
        if os.path.isdir(filename):
            files = self.listdir(filename)
            if not files:
                return beep()
            dirname, filename = filename, files[0]
        else:
            dirname, filename = os.path.split(filename)
        self.load_file(dirname, filename)
        self.save_conf()

    def save_conf(self):
        conf_dir = os.path.split(CONF_FNAME)[0]
        try:
            if not os.path.isdir(conf_dir):
                os.mkdir(conf_dir)
        except IOError:
            logging.exception('Failed attempting to create conf directory: %s', conf_dir)

        conf = {
            'dirname':    self.dirname,
            'filename':   self.filename,
            'compressed': self.is_compressed,
            'linear':     self.is_linear_scale,
            'colormap':   self.cmap,
            'harmonics':  self.harmonics,
            'smooth_slopes': self.use_smoothed_slopes,
            'interpolation': self.wav_interpolation,
            'freq_min':   self.freq_min,
            'freq_max':   self.freq_max,
            'autosave':   self.autosave,
        }
        with open(CONF_FNAME, 'w') as outf:
            logging.debug('Writing conf file: %s', CONF_FNAME)
            outf.write(json.dumps(conf, indent=2))

    def read_conf(self):
        if not os.path.isfile(CONF_FNAME):
            return False
        with open(CONF_FNAME, 'r') as inf:
            logging.debug('Reading conf file: %s', CONF_FNAME)
            conf = json.load(inf)
            self.dirname = conf.get('dirname', '')
            self.filename = conf.get('filename', '')
            self.is_compressed = conf.get('compressed', True)
            self.is_linear_scale = conf.get('linear', True)
            self.cmap = conf.get('colormap', 'gnuplot')
            self.use_smoothed_slopes = conf.get('smooth_slopes', True)
            self.wav_interpolation = conf.get('interpolation', True)
            self.freq_min = conf.get('freq_min', 15)
            self.freq_max = conf.get('freq_max', 100)
            #self.autosave = conf.get('autosave', False)  # TODO: for now, we choose to always start with autosave off
            harmonics = conf.get('harmonics', {'0.5': False, '1': True, '2': False, '3': False})

    def listdir(self, dirname):
        """Produce a list of supported filenames in the specified directory"""
        return [fname for fname in sorted(os.listdir(dirname), key=lambda s: s.lower()) if (
                fnmatch(fname, '*.??#') or fnmatch(fname.lower(), '*.zc') or fnmatch(fname.lower(), '*.wav')
                ) and not fname.startswith('._')   # MacOSX meta-files on a FAT filesystem
        ]

    def on_prev_file(self, event):
        log.debug('prev_file: %s', event)
        files = self.listdir(self.dirname)
        try:
            i = files.index(self.filename)
        except ValueError:
            i = bisect(files, self.filename)  # deleted out from under us?
        if i <= 0:
            return beep()  # we're at the start of the list
        self.load_file(self.dirname, files[i-1])
        self.save_conf()

    def on_next_file(self, event):
        log.debug('next_file: %s', event)
        files = self.listdir(self.dirname)
        try:
            i = files.index(self.filename)
        except ValueError:
            i = bisect(files, self.filename)  # deleted out from under us?
        if i >= len(files) - 1:
            return beep()  # we're at the end of the list
        self.load_file(self.dirname, files[i+1])
        self.save_conf()

    def on_prev_dir(self, event):
        log.debug('prev_dir: %s', event)
        parent, current = os.path.split(self.dirname)
        siblings = [p for p in sorted(os.listdir(parent)) if os.path.isdir(os.path.join(parent, p))]
        try:
            i = siblings.index(current)
        except ValueError:
            i = bisect(siblings, current)  # deleted out from under us?
        if i <= 0:
            return beep()  # we're at the start of the list
        newdir = os.path.join(parent, siblings[i-1])
        files = self.listdir(newdir)
        if not files:
            return beep()  # no anabat files in next dir
        self.load_file(newdir, files[0])
        self.save_conf()

    def on_next_dir(self, event):
        log.debug('next_dir: %s', event)
        parent, current = os.path.split(self.dirname)
        siblings = [p for p in sorted(os.listdir(parent)) if os.path.isdir(os.path.join(parent, p))]
        try:
            i = siblings.index(current)
        except ValueError:
            i = bisect(siblings, current)  # deleted out from under us?
        if i == len(siblings) - 1:
            return beep()  # we're at the end of the list
        newdir = os.path.join(parent, siblings[i+1])
        files = self.listdir(newdir)
        if not files:
            return beep()  # no anabat files in next dir
        self.load_file(newdir, files[0])
        self.save_conf()

    def on_zoom_in(self, event):
        def largest_power_of_two(n):
            if n >= 1.0:
                return 1 << (int(n).bit_length() - 1)
            else:
                return largest_power_of_two(n * 1000) / 1000.0

        if self.window_secs and self.window_secs <= 1.0 / 256:
            return  # max zoom is 1/256 sec (4 ms)

        if self.window_secs is None:
            self.window_secs = largest_power_of_two(self.zc.duration)
        else:
            self.window_secs /= 2
        self.reload_file()

    def on_zoom_out(self, event):
        if self.window_secs and self.window_secs >= 32:
            return  # min zoom is 32 sec (arbitrary)

        if self.window_secs is None:
            return
        self.window_secs *= 2
        self.reload_file()

    def on_zoom_off(self, event):
        self.window_secs = None
        self.window_start = 0.0
        self.reload_file()

    def on_freq_min_change(self, event):
        menu_item = self.GetMenuBar().FindItemById(event.GetId())
        freq = int(menu_item.GetLabel().split()[0])  # yuck! why can't we bind a closure with the freq value itself?!
        log.debug('on_freq_min_change(%s)', freq)
        self.freq_min = freq
        self.reload_file()

    def on_freq_max_change(self, event):
        menu_item = self.GetMenuBar().FindItemById(event.GetId())
        freq = int(menu_item.GetLabel().split()[0])
        log.debug('on_freq_max_change(%s)', freq)
        self.freq_max = freq
        self.reload_file()

    def on_win_forward(self, event):
        if self.window_secs is None:
            return
        window_start = self.window_start + (self.window_secs / 5)
        if window_start >= self.zc.times[-1]:
            window_start = self.zc.times[-1] - self.window_secs
        if window_start < 0:
            window_start = 0  # very short files?
        log.debug('shifting window forward to %.1f sec', window_start)
        self.window_start = window_start
        self.reload_file()

    def on_win_back(self, event):
        if self.window_secs is None:
            return
        window_start = self.window_start - self.window_secs / 5
        if window_start < 0:
            window_start = 0
        log.debug('shifting window backward to %.1f sec', window_start)
        self.window_start = window_start
        self.reload_file()

    def reload_file(self):
        """Re-plot current file without reloading from disk"""
        return self.plot(self.zc)

    def load_file(self, dirname, filename):
        """Called to either load a new file fresh, or load the current file when we've made
        changes that necessitate re-parsing the original file itself."""
        log.debug('\n\nload_file:  %s  %s', dirname, filename)

        if filename != self.filename:
            # reset some file-specific state
            self.window_start = 0.0

            # kill playback since we're switching files
            if self.audio_thread is not None:
                if self.audio_thread.is_playing():
                    self.audio_thread.stop()
                self.audio_thread = None

        path = os.path.join(dirname, filename)
        if not path:
            return

        kwargs = dict(hpfilter_khz=self.hpfilter,
                      divratio=self.wav_divratio,
                      threshold_factor=self.wav_threshold,
                      interpolation=self.wav_interpolation)

        wx.BeginBusyCursor()
        WxMainThread(self.after_load, path, **kwargs)

    def after_load(self, result):
        # callback when we return from asynchronous MainThread
        log.debug('after_load: %s', result)
        if result is not None:
            self.plot(result)

            # only set state upon success
            self.filename = result.metadata['filename']
            self.dirname = os.path.dirname(result.metadata['path'])
            self.zc = result

            if self.autosave:
                self.on_save_file(None)

        wx.EndBusyCursor()

    def plot(self, zc):
        title = title_from_path(zc.metadata.get('path', ''))
        conf = dict(compressed=self.is_compressed, colormap=self.cmap,
                    scale='linear' if self.is_linear_scale else 'log',
                    freqminmax=(self.freq_min, self.freq_max),
                    filter_markers=(self.hpfilter,), harmonics=self.harmonics,
                    smooth_slopes=self.use_smoothed_slopes, display_cursor=self.display_cursor,
                    pulse_markers=self.display_pulse_markers)

        if self.window_secs is not None:
            zc = zc.windowed(self.window_start, self.window_secs)

        try:
            panel = ZeroCrossPlotPanel(self, zc, name=title, config=conf)
            panel.Show()

            self.update_statusbar(zc)

            if self.plotpanel:
                self.plotpanel.Destroy()  # out with the old, in with the new
            self.plotpanel = panel

        except Exception:
            log.exception('Failed plotting %s', zc.metadata.get('filename', ''))

    def _pretty_window_size(self):
        if self.window_secs is None:
            return 'whole file'
        elif self.window_secs >= 1.0:
            return str(self.window_secs) + ' secs'
        else:
            fractional_secs = int(round(1 / self.window_secs))
            ms = int(round(self.window_secs * 1000))
            return '1/%d sec (%d ms)' % (fractional_secs, ms)

    def update_statusbar(self, zc):
        timestamp = zc.metadata.get('timestamp', None) or zc.metadata.get('date', '????-??-??')
        if hasattr(timestamp, 'strftime'):
            timestamp = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        species = ', '.join(zc.metadata.get('species', [])) or '?'
        min_ = np.amin(zc.freqs) / 1000 if zc else -0.0  # TODO: non-zero freqs only
        max_ = np.amax(zc.freqs) / 1000 if zc else -0.0
        divratio = zc.metadata.get('divratio', self.wav_divratio)
        info = 'HPF: %.1f kHz   Sensitivity: %.2f RMS   Div: %d   View: %s' % (self.hpfilter, self.wav_threshold, divratio, self._pretty_window_size())
        self.statusbar.SetStatusText(
            '%s     Dots: %5d     Fmin: %5.1f kHz     Fmax: %5.1f kHz     Species: %s       [%s]'
            % (timestamp, len(zc.freqs), min_, max_, species, info)
        )

    def on_compressed_toggle(self, event):
        log.debug('toggling compressed view (%s)', not self.is_compressed)
        self.is_compressed = not self.is_compressed
        if not self.filename:
            return
        self.reload_file()
        self.save_conf()

    def on_scale_toggle(self, event):
        log.debug('toggling Y scale (%s)', 'linear' if self.is_linear_scale else 'log')
        self.is_linear_scale = not self.is_linear_scale
        self.reload_file()
        self.save_conf()

    def on_smooth_slope_toggle(self, event):
        log.debug('smoothing...' if not self.use_smoothed_slopes else 'un-smoothing...')
        self.use_smoothed_slopes = not self.use_smoothed_slopes
        self.reload_file()
        self.save_conf()  # FIXME: persist this state

    def on_cursor_toggle(self, event):
        log.debug('displaying cursor...' if not self.display_cursor else 'hiding cursor...')
        self.display_cursor = not self.display_cursor
        self.reload_file()
        self.save_conf()  # FIXME: persist this state

    def on_pulse_marker_toggle(self, event):
        log.debug('displaying pulse markers...' if not self.display_pulse_markers else 'hiding pulse markers...')
        self.display_pulse_markers = not self.display_pulse_markers
        self.reload_file()
        self.save_conf()  # FIXME: persist this state

    def on_harmonic_toggle(self, harmonic):
        self.harmonics[harmonic] = not self.harmonics.get(harmonic, False)
        self.reload_file()
        self.save_conf()

    def on_divratio_select(self, divratio):
        self.wav_divratio = divratio
        self.load_file(self.dirname, self.filename)
        self.save_conf()

    def on_interpolation_toggle(self, event):
        log.debug('interpolating .WAV samples' if not self.wav_interpolation else 'disabling .WAV interpolation')
        self.wav_interpolation = not self.wav_interpolation
        self.load_file(self.dirname, self.filename)
        self.save_conf()

    def on_cmap_switch(self, event):
        i = CMAPS.index(self.cmap) + 1
        i %= len(CMAPS) - 1
        self.cmap = CMAPS[i]
        log.debug('switching to colormap: %s', self.cmap)
        self.reload_file()
        self.save_conf()

    def on_cmap_back(self, event):
        i = CMAPS.index(self.cmap) - 1
        i %= len(CMAPS) - 1
        self.cmap = CMAPS[i]
        log.debug('switching to colormap: %s', self.cmap)
        self.reload_file()
        self.save_conf()

    def on_threshold_up(self, event):
        self.wav_threshold += self.WAV_THRESHOLD_DELTA
        self.threshold_slider.set_threshold(self.wav_threshold)
        log.debug('increasing threshold to %.2f RMS', self.wav_threshold)
        self.load_file(self.dirname, self.filename)
        self.save_conf()

    def on_threshold_down(self, event):
        if self.wav_threshold < self.WAV_THRESHOLD_DELTA:
            return
        self.wav_threshold -= self.WAV_THRESHOLD_DELTA
        self.threshold_slider.set_threshold(self.wav_threshold)
        log.debug('decreasing threshold to %.2f RMS', self.wav_threshold)
        self.load_file(self.dirname, self.filename)
        self.save_conf()

    def on_threshold_slider(self, event):
        self.wav_threshold = event.GetEventObject().GetValue() * self.WAV_THRESHOLD_DELTA
        log.debug('slider threshold to %.2f RMS', self.wav_threshold)
        self.load_file(self.dirname, self.filename)
        self.save_conf()

    def on_hpfilter_up(self, event):
        self.hpfilter += self.HPF_DELTA
        log.debug('increasing high-pass filter to %.1f kHz', self.hpfilter)
        self.hpf_spinner.set_hpfcutoff(self.hpfilter)
        self.load_file(self.dirname, self.filename)
        self.save_conf()

    def on_hpfilter_down(self, event):
        if self.hpfilter < self.HPF_DELTA:
            return
        self.hpfilter -= self.HPF_DELTA
        log.debug('decreasing high-pass filter to %.1f kHz', self.hpfilter)
        self.hpf_spinner.set_hpfcutoff(self.hpfilter)
        self.load_file(self.dirname, self.filename)
        self.save_conf()

    def on_hpfilter_spinner(self, event):
        self.hpfilter = event.GetEventObject().GetValue()
        log.debug('spinning high-pass filter to %.1f kHz', self.hpfilter)
        self.load_file(self.dirname, self.filename)
        self.save_conf()


class WxMainThread(MainThread):
    """Main thread handler which hooks back into wx GUI thread upon completion"""

    def on_complete(self, result):
        wx.CallAfter(self.parent_cb, result)
