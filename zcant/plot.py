"""
ZCANT plotting library based on MatPlotLib

---------------
Myotisoft ZCANT
Copyright (C) 2012-2017 Myotisoft LLC, all rights reserved.
You may use, distribute, and modify this code under the terms of the MIT License.
"""

import matplotlib as mpl
import matplotlib.ticker
import matplotlib.gridspec
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.widgets import Cursor, RectangleSelector
from matplotlib.figure import Figure

# FIXME: ideally we want the zcant.plot package to be completely independent of wx
mpl.use('WXAgg')
from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg

import wx

import numpy as np

from zcant import print_timing

import logging
log = logging.getLogger(__name__)


class PlotPanel(wx.Panel):
    """Base class for embedding matplotlib in wx.

    The PlotPanel has a Figure and a Canvas. OnSize events simply set a
    flag, and the actual resizing of the figure is triggered by an Idle event.
    See: http://wiki.scipy.org/Matplotlib_figure_in_a_wx_panel
    """
    # TODO: look into this implementation: http://fides.fe.uni-lj.si/pyopus/doc/wxmplplot.html
    #       http://sukhbinder.wordpress.com/2013/12/19/matplotlib-with-wxpython-example-with-panzoom-functionality/

    def __init__(self, parent, color=None, dpi=None, **kwargs):
        # initialize Panel
        if 'id' not in kwargs.keys():
            kwargs['id'] = wx.ID_ANY
        if 'style' not in kwargs.keys():
            kwargs['style'] = wx.NO_FULL_REPAINT_ON_RESIZE

        self.parent = parent
        wx.Panel.__init__(self, parent, **kwargs)

        # initialize matplotlib stuff
        self.figure = Figure(None, dpi, frameon=True, tight_layout=False)
        self.canvas = FigureCanvasWxAgg(self, -1, self.figure)
        self.SetColor(color)

        # Wire up mouse event
        #self.canvas.mpl_connect('motion_notify_event', self.on_mouse_motion)
        #self.canvas.Bind(wx.EVT_ENTER_WINDOW, self.ChangeCursor)

        self._SetSize()
        self.draw()

        self._resizeflag = False

        self.Bind(wx.EVT_IDLE, self._onIdle)
        self.Bind(wx.EVT_SIZE, self._onSize)

    def SetColor(self, rgbtuple=None):
        """Set figure and canvas colours to be the same."""
        if rgbtuple is None:
            rgbtuple = wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE).Get()
        clr = [c/255. for c in rgbtuple]
        self.figure.set_facecolor(clr)
        self.figure.set_edgecolor(clr)
        self.canvas.SetBackgroundColour(wx.Colour(*rgbtuple))

    def _onSize(self, event):
        self._resizeflag = True

    def _onIdle(self, event):
        if self._resizeflag:
            self._resizeflag = False
            self._SetSize()

    def _SetSize(self):
        pixels = tuple(self.parent.GetClientSize())
        inches = float(pixels[0])/self.figure.get_dpi(), float(pixels[1])/self.figure.get_dpi()
        self.SetSize(pixels)
        self.canvas.SetSize(pixels)
        self.figure.set_size_inches(inches)
        log.debug('_SetSize  DPI: %s  pixels: %s  inches: %s', self.figure.get_dpi(), pixels, inches)

    def on_mouse_motion(self, event):
        pass  # abstract, to be overridden by child classes

    def draw(self):
        pass  # abstract, to be overridden by child classes


class ZeroCrossPlotPanel(PlotPanel):

    SLOPE_MAX = 1000  #750  # highest slope value (oct/sec) of our color scale; TODO: make scale log-based?
    SLOPE_MIN = 0  #-SLOPE_MAX

    config = {  # DEFAULTS
        'freqminmax': (15, 100),   # min and max frequency to display KHz
        'scale': 'linear',         # linear | log
        'markers': (25, 40),       # reference lines kHz
        'filter_markers': (20.0,), # filter lines kHz
        'compressed': False,       # compressed view (True) or realtime (False)
        'smooth_slopes': True,     # smooth out noisy slope values
        'interpolate': True,       # interpolate between WAV samples
        'pulse_markers': True,     # display pulse separators in compressed view
        'display_cursor': False,   # display horiz and vert cursor lines
        'colormap': 'gnuplot',     # named color map
        'dot_sizes': (50, 12, 2),  # dot display sizes in points (max, default, min)
        'harmonics': {'0.5': False, '1': True, '2': False, '3': False},
    }

    def __init__(self, parent, zc, config=None, **kwargs):
        self.zc = zc
        self.times = zc.times if zc else np.array([0.0])
        self.freqs = zc.freqs if zc else np.array([0.0])
        dot_max, dot_default, dot_min = self.config['dot_sizes']
        if zc.supports_amplitude:
            self.amplitudes = zc.amplitudes if zc else np.array([0.0])
            # normalize amplitude values to display point size
            log.debug(' orig. amp  max: %.1f  min: %.1f', np.max(self.amplitudes), np.min(self.amplitudes))
            self.scaled_amplitudes = (zc.amplitudes / np.amax(self.amplitudes)) * (dot_max - dot_min) + dot_min
            log.debug('scaled amp  max: %.1f  min: %.1f', np.max(self.scaled_amplitudes) if len(self.scaled_amplitudes) else 0.0, np.min(self.scaled_amplitudes) if len(self.scaled_amplitudes) else 0.0)
        else:
            self.amplitudes = np.ones(len(zc))
            self.scaled_amplitudes = np.full(len(zc), dot_default)

        self.name = kwargs.get('name', '')
        if config:
            self.config.update(config)

        self.slopes = zc.get_slopes(smooth=self.config['smooth_slopes'])
        self.freqs = self.freqs / 1000  # convert Hz to KHz  (the /= operator doesn't work here?!)

        PlotPanel.__init__(self, parent, **kwargs)

        self.SetColor((0xF0, 0xF0, 0xF0))  # outside border color

    @print_timing
    def draw(self):
        # TODO: recycle the figure with `self.fig.clear()` rather than creating new panel and figure each refresh!

        gs = mpl.gridspec.GridSpec(1, 3, width_ratios=[85, 5, 10], wspace=0.025)

        # --- Main dot scatter plot ---
        self.dot_plot = dot_plot = self.figure.add_subplot(gs[0])

        miny, maxy = self.config['freqminmax']
        plot_kwargs = dict(cmap=self.config['colormap'],
                           vmin=self.SLOPE_MIN, vmax=self.SLOPE_MAX,  # vmin/vmax define where we scale our colormap
                           c=self.slopes, s=self.scaled_amplitudes,   # dot color and size
                           linewidths=0.0,
                           )

        def plot_harmonics(x):
            """Reusable way to plot harmonics from different view types"""
            if self.config['harmonics']['0.5']:
                dot_plot.scatter(x, self.freqs/2, alpha=0.2, **plot_kwargs)
            if self.config['harmonics']['2']:
                dot_plot.scatter(x, self.freqs*2, alpha=0.2, **plot_kwargs)
            if self.config['harmonics']['3']:
                dot_plot.scatter(x, self.freqs*3, alpha=0.2, **plot_kwargs)

        if len(self.freqs) < 2:
            dot_scatter = dot_plot.scatter([], [])  # empty set

        elif not self.config['compressed']:
            # Realtime View
            plot_harmonics(self.times)
            dot_scatter = dot_plot.scatter(self.times, self.freqs, **plot_kwargs)
            dot_plot.set_xlim(self.times[0], self.times[-1])
            dot_plot.set_xlabel('Time (sec)')

        else:
            # Compressed (pseudo-Dot-Per-Pixel) View

            if self.config['pulse_markers']:
                for v in self.zc.get_pulses():
                    dot_plot.axvline(v, linewidth=0.5, color='#808080')

            x = range(len(self.freqs))
            plot_harmonics(x)
            dot_scatter = dot_plot.scatter(x, self.freqs, **plot_kwargs)
            dot_plot.set_xlim(0, len(x))
            dot_plot.set_xlabel('Dot Count')

        try:
            dot_plot.set_yscale(self.config['scale'])  # FIXME: fails with "Data has no positive values" error
        except ValueError:
            log.exception('Failed setting log scale (exception caught)')
            log.error('\ntimes: %s\nfreqs: %s\nslopes: %s', self.times, self.freqs, self.slopes)

        dot_plot.set_title(self.name)
        dot_plot.set_ylabel('Frequency (kHz)')
        dot_plot.set_ylim(miny, maxy)

        # remove the default tick labels, then produce our own instead
        dot_plot.yaxis.set_minor_formatter(mpl.ticker.NullFormatter())
        dot_plot.yaxis.set_major_formatter(mpl.ticker.ScalarFormatter())
        minytick = miny if miny % 10 == 0 else miny + 10 - miny % 10  # round up to next 10kHz tick
        maxytick = maxy if maxy % 10 == 0 else maxy + 10 - maxy % 10
        ticks = range(minytick, maxytick+1, 10)   # labels every 10kHz
        dot_plot.yaxis.set_ticks(ticks)

        dot_plot.set_axisbelow(True)
        dot_plot.grid(axis='y', which='both', linestyle=':')

        for freqk in self.config['markers']:
            dot_plot.axhline(freqk, color='r', linewidth=1.0, zorder=0.9)

        for freqk in self.config['filter_markers']:
            dot_plot.axhline(freqk, color='b', linestyle='--', linewidth=1.1, zorder=0.95)

        # draw X and Y cursor; this may beform better if we can use Wx rather than MatPlotLib, see `wxcursor_demo.py`
        if self.config['display_cursor']:
            self.cursor1 = Cursor(dot_plot, useblit=True, color='black', linewidth=1)

        # experimental rectangle selection
        def onselect(eclick, erelease):
            """eclick and erelease are matplotlib events at press and release"""
            x1, y1 = eclick.xdata, eclick.ydata
            x2, y2 = erelease.xdata, erelease.ydata
            log.debug(' Select  (%.3f,%.1f) -> (%.3f,%.1f)  button: %d' % (x1, y1, x2, y2, eclick.button))
            if self.config['compressed']:
                x1, x2 = self.zc.times[int(round(x1))], self.zc.times[int(round(x2))]
            slope = (np.log2(y2) - np.log2(y1)) / (x2 - x1)
            log.debug('         slope: %.1f oct/sec  (%.1f kHz / %.3f sec)' % (slope, y2 - y1, x2 - x1))

        self.selector = RectangleSelector(dot_plot, onselect, drawtype='box')
        #connect('key_press_event', toggle_selector)

        # --- Colorbar plot ---
        self.cbar_plot = cbar_plot = self.figure.add_subplot(gs[1])
        cbar_plot.set_title('Slope')
        try:
            cbar = self.figure.colorbar(dot_scatter, cax=cbar_plot, ticks=[])
        except TypeError:
            # colorbar() blows up on empty set
            sm = ScalarMappable(cmap=self.config['colormap'])  # TODO: this should probably share colormap code with histogram
            sm.set_array(np.array([self.SLOPE_MIN, self.SLOPE_MAX]))
            cbar = self.figure.colorbar(sm, cax=cbar_plot, ticks=[])
        cbar.ax.set_yticklabels([])

        # --- Hist plot ---

        self.hist_plot = hist_plot = self.figure.add_subplot(gs[2])
        hist_plot.set_title('Freqs')

        bin_min, bin_max = self.config['freqminmax']
        bin_size = 2  # khz  # TODO: make this configurable
        bin_n = int((bin_max - bin_min) / bin_size)
        n, bins, patches = hist_plot.hist(self.freqs, weights=self.amplitudes,
                                          range=self.config['freqminmax'], bins=bin_n,
                                          orientation='horizontal',
                                          edgecolor='black')
        hist_plot.set_yscale(self.config['scale'])
        hist_plot.set_ylim(miny, maxy)
        hist_plot.yaxis.set_major_formatter(mpl.ticker.ScalarFormatter())

        # color histogram bins
        cmap = ScalarMappable(cmap=self.config['colormap'], norm=Normalize(vmin=self.SLOPE_MIN, vmax=self.SLOPE_MAX))
        for bin_start, bin_end, patch in zip(bins[:-1], bins[1:], patches):
            bin_mask = (bin_start <= self.freqs) & (self.freqs < bin_end)
            bin_slopes = self.slopes[bin_mask]
            slope_weights = self.scaled_amplitudes[bin_mask]
            avg_slope = np.average(bin_slopes, weights=slope_weights) if bin_slopes.any() else 0.0
            #avg_slope = np.median(bin_slopes) if bin_slopes.any() else 0
            patch.set_facecolor(cmap.to_rgba(avg_slope))

        hist_plot.yaxis.set_minor_formatter(mpl.ticker.NullFormatter())
        hist_plot.yaxis.set_ticks(ticks)
        hist_plot.yaxis.tick_right()

        hist_plot.xaxis.set_ticks([])

        hist_plot.set_axisbelow(True)
        hist_plot.grid(axis='y', which='both', linestyle=':')

        for freqk in self.config['markers']:
            hist_plot.axhline(freqk, color='r', linewidth=1.0, zorder=0.9)

        for freqk in self.config['filter_markers']:
            hist_plot.axhline(freqk, color='b', linestyle='--', linewidth=1.1, zorder=0.95)

        # draw Y cursor
        if self.config['display_cursor']:
            self.cursor3 = Cursor(hist_plot, useblit=True, color='black', linewidth=1, vertOn=False, horizOn=True)

    # def on_mouse_motion(self, event):
    #     if event.inaxes:
    #         x, y = event.xdata, event.ydata
    #         print '%.1fkHz, %.1f' % (y, x)
