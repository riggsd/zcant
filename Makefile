
PYTHON=python

VERSION = $(shell grep __version__ zcant.py | cut -d "'" -f 2)

all: clean build

clean:
	rm -rf build dist

build:
	$(PYTHON) setup.py py2app

test:
	$(PYTHON) -m unittest discover -v -s unittests

pep8:
	pep8 --max-line-length=120 zcant

pylint:
	pylint -f colorized --errors-only zcant
