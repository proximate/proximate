#!/bin/sh

VERSION=$(cat version)

./configure --prefix=/usr "$@"
if test "$?" != "0" ; then
    echo
    echo "Configure failed. Can not create a deb package."
    echo "Are you in the main directory that contains the configure script?"
    exit 1
fi

sed -e "s|{VERSION}|$VERSION|g" < deb/control.in > deb/control

dname="proximate-$VERSION"
if test -e "$dname" ; then
    rm -rf "$dname"
fi

umask 0022
make install DESTDIR="$dname"

control="deb/control"
mkdir -m 755 -p "$dname"/DEBIAN/
install -m 644 "$control" "$dname"/DEBIAN/control

VERSION=`cat "$control" | grep "^Version" | cut -d ' ' -f 2`
ARCH=`cat "$control" | grep "^Architecture" | cut -d ' ' -f 2`
fakeroot dpkg-deb -b "$dname" proximate_"$VERSION"_"$ARCH".deb
