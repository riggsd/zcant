#!/bin/bash

set -e

#FRAMEWORK_EXCLUDES="PyQT PROJ PIL phonon QtCore QtDeclarative QtDesigner QtGui QtHelp QtMultimedia QtNetwork QtOpenGL QtScript QtScriptTools QtSql QtSvg QtTest QtWebKit QtXml QtXmlPatterns"

# clean
rm -rf ./build ./dist

# build
nice time python setup.py py2app

# strip that bloated pig
echo "before stripping"
du -h -d 1 dist

#for FRAMEWORK in $FRAMEWORK_EXCLUDES; do
#    rm -rf dist/ZCView.app/Contents/Frameworks/${FRAMEWORK}.framework
#done

JUNK="tests doc docs"
for DIR in $JUNK; do
    find dist/ZCView.app/Contents/Resources/lib/python2.7/ -name $DIR | xargs rm -rf
done
rm -rf dist/ZCView.app/Contents/Resources/mpl-data/sample_data

echo "after stripping"
du -h -d 1 dist
