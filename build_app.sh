#!/bin/bash

set -e

APP=dist/zcant.app

#FRAMEWORK_EXCLUDES="PyQT PROJ PIL phonon QtCore QtDeclarative QtDesigner QtGui QtHelp QtMultimedia QtNetwork QtOpenGL QtScript QtScriptTools QtSql QtSvg QtTest QtWebKit QtXml QtXmlPatterns"

# clean
rm -rf ./build ./dist

# build
nice time python setup.py py2app

# strip that bloated pig
echo "before stripping"
du -h -d 1 dist

#for FRAMEWORK in $FRAMEWORK_EXCLUDES; do
#    rm -rf dist/zcant.app/Contents/Frameworks/${FRAMEWORK}.framework
#done

JUNK="test tests nose doc docs sample_data"
for DIR in $JUNK; do
    find $APP/Contents/Resources/lib/python2.7/ -name $DIR | xargs rm -rf
done
rm -rf $APP/Contents/Resources/mpl-data/sample_data

echo "after stripping"
du -h -d 1 dist
