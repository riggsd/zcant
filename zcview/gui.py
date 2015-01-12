"""
ZCView GUI
"""

# See: http://wiki.scipy.org/Cookbook/Matplotlib/EmbeddingInWx
#
#

import os
import os.path
import json
from fnmatch import fnmatch

import wx

import numpy as np

import matplotlib
matplotlib.interactive(True)
matplotlib.use('WXAgg')
from matplotlib.figure import Figure
import matplotlib.ticker
import matplotlib.gridspec

from zcview import print_timing
from zcview.anabat import extract_anabat
from zcview.conversion import wav2zc

import logging
log = logging.getLogger(__name__)


CONF_FNAME = os.path.expanduser('~/.myotisoft/zcview.ini')


CMAP_SEQ  = ['Blues', 'BuGn', 'BuPu', 'GnBu', 'Greens', 'Greys', 'Oranges', 'OrRd', 'PuBu', 'PuBuGn', 'PuRd', 'Purples', 'RdPu', 'Reds', 'YlGn', 'YlGnBu', 'YlOrBr', 'YlOrRd']
CMAP_SEQ2 = ['afmhot', 'autumn', 'bone', 'cool', 'copper', 'gist_heat', 'gray', 'hot', 'pink', 'spring', 'summer', 'winter']
CMAP_DIV  = ['BrBG', 'bwr', 'coolwarm', 'PiYG', 'PRGn', 'PuOr', 'RdBu', 'RdGy', 'RdYlBu', 'RdYlGn', 'Spectral', 'seismic']
CMAP_QUAL = ['Accent', 'Dark2', 'Paired', 'Pastel1', 'Pastel2', 'Set1', 'Set2', 'Set3']
CMAP_MISC = ['gist_earth', 'terrain', 'ocean', 'gist_stern', 'brg', 'CMRmap', 'cubehelix', 'gnuplot', 'gnuplot2', 'gist_ncar', 'nipy_spectral', 'jet', 'rainbow', 'gist_rainbow', 'hsv', 'flag', 'prism']
CMAPS = CMAP_SEQ + CMAP_SEQ2 + CMAP_DIV + CMAP_QUAL + CMAP_MISC


def title_from_path(path):
    root, fname = os.path.split(path)
    root, parent = os.path.split(root)
    root, gparent = os.path.split(root)
    if gparent:
        return '%s %s %s %s %s' % (gparent, os.sep, parent, os.sep, fname)
    elif parent:
        return '%s %s %s' % (parent, os.sep, fname)
    else:
        return fname


class ZCViewMainFrame(wx.Frame):

    def __init__(self, parent, title='Myotisoft ZCView'):
        wx.Frame.__init__(self, parent, title=title, size=(640,480))

        # Application State
        self.dirname = ''
        self.filename = ''
        self.is_compressed = True
        self.is_linear_scale = True
        self.cmap = 'jet'
        self.wav_threshold = 1.0
        self.hpfilter = 20.0
        self.read_conf()

        self.init_gui()

        if self.dirname and self.filename:
            try:
                self.load_file(self.dirname, self.filename)
            except Exception, e:
                log.exception('Failed opening default file: %s', os.path.join(self.dirname, self.filename))

    def init_gui(self):
        self.plotpanel = None

        # Menu Bar
        menu_bar = wx.MenuBar()

        file_menu = wx.Menu()
        open_item = file_menu.Append(wx.ID_OPEN, '&Open', ' Open a zero-cross file')
        self.Bind(wx.EVT_MENU, self.on_open, open_item)
        about_item = file_menu.Append(wx.ID_ABOUT, '&About', ' Information about this program')
        self.Bind(wx.EVT_MENU, self.on_about, about_item)
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, 'E&xit', ' Terminate this program')
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        menu_bar.Append(file_menu, '&File')
        self.SetMenuBar(menu_bar)

        # Nav Toolbar
        tool_bar = self.CreateToolBar( wx.TB_TEXT)
        open_item = tool_bar.AddLabelTool(wx.ID_ANY, 'Open',       wx.Bitmap('resources/icons/file-8x.png'), shortHelp='Open')
        self.Bind(wx.EVT_TOOL, self.on_open, open_item)

        tool_bar.AddSeparator()
        prev_dir  = tool_bar.AddLabelTool(wx.ID_ANY, 'Prev Folder', wx.Bitmap('resources/icons/chevron-left-8x.png'),
                                          shortHelp='Prev folder', longHelp='Open the previous folder (or use the `{` key)')
        self.Bind(wx.EVT_TOOL, self.on_prev_dir, prev_dir)
        prev_file = tool_bar.AddLabelTool(wx.ID_ANY, 'Prev File',   wx.Bitmap('resources/icons/caret-left-8x.png'),
                                          shortHelp='Prev file', longHelp='Open the previous file in this folder (or use `[` key)')
        self.Bind(wx.EVT_TOOL, self.on_prev_file, prev_file)
        next_file = tool_bar.AddLabelTool(wx.ID_ANY, 'Next File',   wx.Bitmap('resources/icons/caret-right-8x.png'),
                                          shortHelp='Next file', longHelp='Open the next file in this folder (or use the `]` key)')
        self.Bind(wx.EVT_TOOL, self.on_next_file, next_file)
        next_dir  = tool_bar.AddLabelTool(wx.ID_ANY, 'Next Folder', wx.Bitmap('resources/icons/chevron-right-8x.png'),
                                          shortHelp='Next folder', longHelp='Open the next folder (or use the `}` key)')
        self.Bind(wx.EVT_TOOL, self.on_next_dir, next_dir)

        tool_bar.AddSeparator()
        toggle_compressed = tool_bar.AddLabelTool(wx.ID_ANY, 'Compressed', wx.Bitmap('resources/icons/audio-spectrum-8x.png'),
                                                  shortHelp='Toggle compressed', longHelp='Toggle compressed view on/off (or use the `c` key)')
        self.Bind(wx.EVT_TOOL, self.on_compressed_toggle, toggle_compressed)

        tool_bar.AddSeparator()

        #self.SetToolBar(tool_bar)
        tool_bar.Realize()

        # Main layout
        #self.main_grid = wx.FlexGridSizer(rows=2)

        # Control Panel
        #self.control_panel = wx.Panel(self)
        #self.threshold_spinctl = wx.SpinCtrl(self, value=str(self.wav_threshold))  #, pos=(150, 75), size=(60, -1))
        #self.threshold_spinctl.SetRange(0.0, 10.0)

        # Status Bar
        self.statusbar = self.CreateStatusBar()

        # Key Bindings
        prev_file_id, next_file_id, prev_dir_id, next_dir_id = wx.NewId(), wx.NewId(), wx.NewId(), wx.NewId()
        compressed_id, scale_id, cmap_id, cmap_back_id = wx.NewId(), wx.NewId(), wx.NewId(), wx.NewId()
        threshold_up_id, threshold_down_id, hpfilter_up_id, hpfilter_down_id = wx.NewId(), wx.NewId(), wx.NewId(), wx.NewId()
        self.Bind(wx.EVT_MENU, self.on_prev_file, id=prev_file_id)
        self.Bind(wx.EVT_MENU, self.on_next_file, id=next_file_id)
        self.Bind(wx.EVT_MENU, self.on_prev_dir,  id=prev_dir_id)
        self.Bind(wx.EVT_MENU, self.on_next_dir,  id=next_dir_id)
        self.Bind(wx.EVT_MENU, self.on_compressed_toggle, id=compressed_id)
        self.Bind(wx.EVT_MENU, self.on_scale_toggle, id=scale_id)
        self.Bind(wx.EVT_MENU, self.on_cmap_switch, id=cmap_id)
        self.Bind(wx.EVT_MENU, self.on_cmap_back,   id=cmap_back_id)
        self.Bind(wx.EVT_MENU, self.on_threshold_up, id=threshold_up_id)
        self.Bind(wx.EVT_MENU, self.on_threshold_down, id=threshold_down_id)
        self.Bind(wx.EVT_MENU, self.on_hpfilter_up, id=hpfilter_up_id)
        self.Bind(wx.EVT_MENU, self.on_hpfilter_down, id=hpfilter_down_id)
        a_table = wx.AcceleratorTable([
            (wx.ACCEL_NORMAL, ord('['), prev_file_id),
            (wx.ACCEL_NORMAL, ord(']'), next_file_id),
            (wx.ACCEL_SHIFT,  ord('['), prev_dir_id),  # {
            (wx.ACCEL_SHIFT,  ord(']'), next_dir_id),  # }
            (wx.ACCEL_NORMAL, ord(' '), compressed_id),
            (wx.ACCEL_NORMAL, ord('l'), scale_id),
            (wx.ACCEL_NORMAL, ord('p'), cmap_id),
            (wx.ACCEL_SHIFT,  ord('p'), cmap_back_id),
            (wx.ACCEL_NORMAL, wx.WXK_UP, threshold_up_id),
            (wx.ACCEL_NORMAL, wx.WXK_DOWN, threshold_down_id),
            (wx.ACCEL_SHIFT,  wx.WXK_UP, hpfilter_up_id),
            (wx.ACCEL_SHIFT,  wx.WXK_DOWN, hpfilter_down_id),
        ])
        self.SetAcceleratorTable(a_table)

    def on_about(self, event):
        log.debug('about: %s', event)
        dlg = wx.MessageDialog(self, 'A boring Zero-Cross Viewer!', 'About ZCView', wx.OK)
        dlg.ShowModal()
        dlg.Destroy()

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

    def save_conf(self):
        conf_dir = os.path.split(CONF_FNAME)[0]
        try:
            if not os.path.isdir(conf_dir):
                os.mkdir(conf_dir)
        except IOError, e:
            logging.exception('Failed attempting to create conf directory: %s', conf_dir)

        conf = {
            'dirname':    self.dirname,
            'filename':   self.filename,
            'compressed': self.is_compressed,
            'linear':     self.is_linear_scale,
            'colormap':   self.cmap,
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
            self.cmap = conf.get('colormap', 'jet')

    def on_prev_file(self, event):
        log.debug('prev_file: %s', event)
        files = [fname for fname in os.listdir(self.dirname) if fnmatch(fname, '*.??#') or fnmatch(fname.lower(), '*.zc') or (fnmatch(fname.lower(), '*.wav') and not fname.startswith('._'))]
        i = files.index(self.filename)
        if i <= 0:
            return  # we're at the start of the list
        self.load_file(self.dirname, files[i-1])
        self.save_conf()

    def on_next_file(self, event):
        log.debug('next_file: %s', event)
        files = [fname for fname in os.listdir(self.dirname) if fnmatch(fname, '*.??#') or fnmatch(fname.lower(), '*.zc') or (fnmatch(fname.lower(), '*.wav') and not fname.startswith('._'))]
        i = files.index(self.filename)
        if i == len(files) - 1:
            return  # we're at the end of the list
        self.load_file(self.dirname, files[i+1])
        self.save_conf()

    def on_prev_dir(self, event):
        log.debug('prev_dir: %s', event)
        parent, current = os.path.split(self.dirname)
        siblings = [p for p in os.listdir(parent) if os.path.isdir(os.path.join(parent, p))]
        i = siblings.index(current)
        if i <= 0:
            return  # we're at the start of the list
        newdir = os.path.join(parent, siblings[i-1])
        files = [fname for fname in os.listdir(newdir) if fnmatch(fname, '*.??#') or fnmatch(fname.lower(), '*.zc') or (fnmatch(fname.lower(), '*.wav') and not fname.startswith('._'))]
        if not files:
            return  # no anabat files in next dir
        self.load_file(newdir, files[0])
        self.save_conf()

    def on_next_dir(self, event):
        log.debug('next_dir: %s', event)
        parent, current = os.path.split(self.dirname)
        siblings = [p for p in os.listdir(parent) if os.path.isdir(os.path.join(parent, p))]
        i = siblings.index(current)
        if i == len(siblings) - 1:
            return  # we're at the end of the list
        newdir = os.path.join(parent, siblings[i+1])
        files = [fname for fname in os.listdir(newdir) if fnmatch(fname, '*.??#') or fnmatch(fname.lower(), '*.zc') or (fnmatch(fname.lower(), '*.wav') and not fname.startswith('._'))]
        if not files:
            return  # no anabat files in next dir
        self.load_file(newdir, files[0])
        self.save_conf()

    def extract(self, path):
        """Extract (times, freqs, metadata) from supported filetypes"""
        ext = os.path.splitext(path)[1].lower()
        if ext.endswith('#') or ext == '.zc':
            return extract_anabat(path, hpfilter_khz=self.hpfilter)
        elif ext == '.wav':
            return wav2zc(path, threshold_factor=self.wav_threshold, hpfilter_khz=self.hpfilter)
        else:
            raise Exception('Unknown file type: %s', path)

    def load_file(self, dirname, filename):
        log.debug('\n\nload_file:  %s  %s', dirname, filename)
        path = os.path.join(dirname, filename)
        if not path:
            return

        times, freqs, metadata = self.extract(path)
        metadata['path'] = path
        metadata['filename'] = filename
        log.debug('    %s:  times: %d  freqs: %d', filename, len(times), len(freqs))

        self.plot(times, freqs, metadata)

        self.dirname, self.filename, self._times, self._freqs, self._metadata = dirname, filename, times, freqs, metadata  # only set on success

    def plot(self, times, freqs, metadata):
        title = title_from_path(metadata.get('path', ''))
        conf = dict(compressed=self.is_compressed, colormap=self.cmap, scale='linear' if self.is_linear_scale else 'log', filter_markers=(self.hpfilter,))
        try:
            panel = ZeroCrossPlotPanel(self, times, freqs, name=title, config=conf)
            panel.Show()

            min_, max_ = min(f for f in freqs if f >= 100)/1000.0, max(freqs)/1000.0  # TODO: replace with np.amax when we switch
            self.statusbar.SetStatusText(
                '%s     Dots: %5d     Fmin: %5.1fkHz     Fmax: %5.1fkHz     Species: %s'
                % (metadata.get('timestamp', None) or metadata.get('date', ''),
                   len(freqs), min_, max_, ', '.join(metadata.get('species',[]))))

            if self.plotpanel:
                self.plotpanel.Destroy()  # out with the old, in with the new
            self.plotpanel = panel

        except Exception, e:
            log.exception('Failed plotting %s', metadata.get('filename', ''))

    def reload_file(self):
        """Re-plot without reloading file from disk"""
        return self.plot(self._times, self._freqs, self._metadata)

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
        self.wav_threshold += 0.2
        log.debug('increasing threshold to %.1f x RMS', self.wav_threshold)
        self.load_file(self.dirname, self.filename)
        self.save_conf()

    def on_threshold_down(self, event):
        if self.wav_threshold < 0.2:
            return
        self.wav_threshold -= 0.2
        log.debug('decreasing threshold to %.1f x RMS', self.wav_threshold)
        self.load_file(self.dirname, self.filename)
        self.save_conf()

    def on_hpfilter_up(self, event):
        self.hpfilter += 2.5
        log.debug('increasing high-pass filter to %.1f KHz', self.hpfilter)
        self.load_file(self.dirname, self.filename)
        self.save_conf()

    def on_hpfilter_down(self, event):
        self.hpfilter -= 2.5
        log.debug('decreasing high-pass filter to %.1f KHz', self.hpfilter)
        self.load_file(self.dirname, self.filename)
        self.save_conf()


class PlotPanel(wx.Panel):
    """Base class for embedding matplotlib in wx.

    The PlotPanel has a Figure and a Canvas. OnSize events simply set a
    flag, and the actual resizing of the figure is triggered by an Idle event.
    See: http://wiki.scipy.org/Matplotlib_figure_in_a_wx_panel
    """
    # TODO: look into this implementation: http://fides.fe.uni-lj.si/pyopus/doc/wxmplplot.html
    #       http://sukhbinder.wordpress.com/2013/12/19/matplotlib-with-wxpython-example-with-panzoom-functionality/

    def __init__(self, parent, color=None, dpi=None, **kwargs):
        from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg
        from matplotlib.figure import Figure

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


@print_timing
def slopes(x, y):
    """
    Produce an array of slope values in octaves per second.
    We very, very crudely try to compensate for the jump between pulses, but don't deal well with noise.
    :param x:
    :param y:
    :return:
    """
    if not len(x) or not len(y):
        return np.array([])
    elif len(x) == 1:
        return np.array([0.0])
    slopes = np.diff(np.log2(y)) / np.diff(np.log2(x))
    slopes = np.append(slopes, slopes[-1])  # hack for final dot
    slopes = -1 * slopes  # Analook inverts slope so we do also
    log.debug('Smax: %d OPS   Smin: %d OPS', np.amax(slopes), np.amin(slopes))
    slopes[slopes < -5000] = 0.0  # super-steep is probably noise or a new pulse
    slopes[slopes > 10000] = 0.0  # TODO: refine these magic boundary values!
    return slopes


class ZeroCrossPlotPanel(PlotPanel):

    config = {
        'freqminmax': (15, 100),   # min and max frequency to display KHz
        'scale': 'linear',         # linear | log
        'markers': (25, 40),       # reference lines kHz
        'filter_markers': (20.0,), # reference lines kHz
        'compressed': False,       # compressed view (True) or realtime (False)
        'colormap': 'jet'          # named color map
    }

    def __init__(self, parent, times, freqs, config=None, **kwargs):
        self.times = times if len(times) else np.array([0.0])
        self.freqs = freqs if len(freqs) else np.array([0.0])
        self.slopes = slopes(self.times, self.freqs)
        self.freqs = self.freqs / 1000  # convert Hz to KHz
        self.name = kwargs.get('name', '')
        if config:
            self.config.update(config)

        PlotPanel.__init__(self, parent, **kwargs)

        self.SetColor((0xff, 0xff, 0xff))

    def draw(self):
        # TODO: recycle the figure with `self.fig.clear()` rather than creating new panel and figure each refresh!

        gs = matplotlib.gridspec.GridSpec(1, 3, width_ratios=[85, 5, 10], wspace=0.025)

        # Main dot scatter plot
        self.dot_plot = self.figure.add_subplot(gs[0]) #axes([0,0,1.0,1.0])  #[0, 0, 0.84, 1.0])

        miny, maxy = self.config['freqminmax']
        plot_kwargs = dict(cmap=self.config['colormap'], vmin=0, vmax=600, linewidths=0.0)  # vmin/vmax define where we scale our colormap
        # TODO: neither of these are proper compressed or non-compressed views!
        if len(self.freqs) < 2:
            dot_scatter = self.dot_plot.scatter([], [])  # empty set
        elif self.config['compressed']:
            dot_scatter = self.dot_plot.scatter(self.times, self.freqs, c=self.slopes, **plot_kwargs)
            self.dot_plot.set_xlim(self.times[0], self.times[-1])
            self.dot_plot.set_xlabel('Time (sec)')
        else:
            x = range(len(self.freqs))
            dot_scatter = self.dot_plot.scatter(x, self.freqs, c=self.slopes, **plot_kwargs)
            self.dot_plot.set_xlim(0, len(x))
            self.dot_plot.set_xlabel('Dot Count')

        self.dot_plot.set_title(self.name)
        self.dot_plot.set_yscale(self.config['scale'])
        self.dot_plot.set_ylim(miny, maxy)
        self.dot_plot.set_ylabel('Frequency (KHz)')

        self.dot_plot.get_yaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
        minytick = miny if miny % 10 == 0 else miny + 10 - miny % 10  # round up to next 10kHz tick
        maxytick = maxy if maxy % 10 == 0 else maxy + 10 - maxy % 10
        ticks = range(minytick, maxytick+1, 10)   # labels every 10kHz
        self.dot_plot.get_yaxis().set_ticks(ticks)

        self.dot_plot.grid(axis='y', which='both')

        for freqk in self.config['markers']:
            self.dot_plot.axhline(freqk, color='r')

        for freqk in self.config['filter_markers']:
            self.dot_plot.axhline(freqk, color='b', linestyle='--')

        # Colorbar plot
        cbar_plot = self.figure.add_subplot(gs[1]) #axes([0.85, 0, 0.05, 1.0])
        cbar_plot.set_title('Slope')
        cbar = self.figure.colorbar(dot_scatter, cax=cbar_plot, ticks=[])
        cbar.ax.set_yticklabels([])

        # Hist plot

        hist_plot = self.figure.add_subplot(gs[2]) #axes([0.91, 0, 0.09, 1.0], sharey=self.dot_plot)
        hist_plot.set_title('Freqs')

        bins = int(round((maxy - miny) / 2.5))
        hist_plot.hist(self.freqs, orientation='horizontal', bins=bins)
        hist_plot.set_yscale(self.config['scale'])
        hist_plot.set_ylim(miny, maxy)
        hist_plot.get_yaxis().set_ticks(ticks)
        hist_plot.yaxis.tick_right()
        hist_plot.grid(axis='y', which='both')
        hist_plot.xaxis.set_ticks([])

        for freqk in self.config['markers']:
            hist_plot.axhline(freqk, color='r')

        for freqk in self.config['filter_markers']:
            hist_plot.axhline(freqk, color='b', linestyle='--')

    def on_mouse_motion(self, event):
        if event.inaxes:
            x, y = event.xdata, event.ydata
            #print x, y
