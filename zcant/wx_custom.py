"""
Custom wx widgets for use with the ZCANT GUI

---------------
Myotisoft ZCANT
Copyright (C) 2012-2017 Myotisoft LLC, all rights reserved.
You may use, distribute, and modify this code under the terms of the MIT License.
"""

import wx
from wx.lib.agw.floatspin import FloatSpin, FS_CENTRE, FS_READONLY, EVT_FLOATSPIN

import logging
log = logging.getLogger(__name__)


__all__ = 'ThresholdToolbarSlider', 'HpfToolbarSpinner', 'EVT_FLOATSPIN'


class ThresholdToolbarSlider(wx.Slider):
    """A scaled-value slider which, when embedded in a toolbar, updates the toolbar label"""
    # sliders only work with integer values, so we scale back and forth between slider-threshold
    def __init__(self, parent_toolbar, threshold, delta, minValue=0, maxValue=10, **kwargs):
        wx.Slider.__init__(self, parent_toolbar, wx.ID_ANY, threshold/delta, minValue, maxValue/delta, **kwargs)
        self._threshold = threshold
        self._delta = delta
        self._tool = parent_toolbar.AddControl(self, 'Sensitivity %.2f RMS' % threshold)
        self._update_label(self._threshold)
        self.Bind(wx.EVT_SCROLL_THUMBTRACK, lambda e: self._update_label(e.GetEventObject().GetValue() * self._delta))

    def _update_label(self, threshold):
        self._tool.SetLabel('Sensitivity %.2f RMS' % threshold)

    def set_threshold(self, threshold):
        """Set a new threshold value from an external control"""
        self._threshold = threshold
        self.SetValue(threshold / self._delta)
        self._update_label(threshold)

    @property
    def threshold(self):
        return self._threshold


class HpfToolbarSpinner(FloatSpin):
    """A spinner box for HPF control embedded in a toolbar"""
    # FIXME: HIGH PRIORITY: currently set to readonly because our ZcantMainFrame KeyEvent listener intercepts the number '0'!

    def __init__(self, parent_toolbar, hpfcutoff, delta,
                 minValue=0, maxValue=100, digits=1, style=FS_CENTRE|FS_READONLY):
        FloatSpin.__init__(self, parent_toolbar,
                           value=hpfcutoff, min_val=minValue, max_val=maxValue,
                           increment=delta, digits=digits, agwStyle=style)
        self._tool = parent_toolbar.AddControl(self, 'HPF kHz')

        # we currently render plots too slowly to deal with mousewheel events; disconnect them
        self._textctrl.Unbind(wx.EVT_MOUSEWHEEL)
        self._spinbutton.Unbind(wx.EVT_MOUSEWHEEL)

    def OnChar(self, event):
        log.debug('HpfToolbarSpinner.OnChar() %s', event.GetKeyCode())
        FloatSpin.OnChar(self, event)
        event.Skip(False)  # fix a bug in `agw.FloatSpin.OnChar()`

    def set_hpfcutoff(self, hpfcutoff):
        self.SetValue(hpfcutoff)

    @property
    def hpfcutoff(self):
        return self.GetValue()
