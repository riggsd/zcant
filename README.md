= Myotisoft ZCANT

ZCANT is a tool for analyzing bat echolocation calls. Specifically, it extracts the echolocation
signal using the zero-crossing technique pioneered by Chris Corben, with a few modern twists:

- Digital signal processing techniques are used to enhance the audio during the zero-cross
  extraction.

- Amplitude from the original full-spectrum signal is integrated into the zero-cross display
  visually, essentially providing the "best of both worlds".

- Slope, the most important derived parameter of a time/frequency zero-cross signal, is integrated
  into the display visually as color. You'll soon develop a synesthesia that lets you see the shape
  of a call by its colors.

![ZCANT Screenshot](/docs/images/zcan_screenshot.png?raw=true "ZCANT Screenshot")


== License

ZCANT is Free / Open Source Software, cross-platform, and written in the Python programming
language. It can serve as the base for your own bat acoustics software projects! See the file
`LICENSE.txt` for details of the MIT License.

Copyright (C) 2012-2017 by Myotisoft LLC <http://myotisoft.com>


== Requirements

- Python 2.7
- NumPy
- SciPy
- MatPlotLib


== Building

Install wxPython 3.0.1.1. See: https://wiki.wxpython.org/How%20to%20install%20wxPython

pip -r requirements.txt

python ZCView.py

