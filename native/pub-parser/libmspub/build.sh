#!/bin/sh
# Builds libmspub 0.1.4 from LibreOffice's release tarball, with this
# repository's patches, into a private prefix (default /opt/libmspub).
#
# Why a patched build rather than the distribution's package: libmspub reads
# things it never passes on. Paragraph lists are parsed into m_listInfo and
# never written out (patches/0001), and PUB-001's numbered lists were lost.
# libmspub has had no release since 0.1.4, so a small patch set stays put.
# The tarball is checked against its SHA-256 before anything is built.
#
# Needs: a C++ compiler, make, pkg-config, patch, curl, xz, and the
# librevenge, ICU, Boost and zlib development headers.
#
#   native/pub-parser/libmspub/build.sh [prefix]
set -eu

VERSION=0.1.4
SHA256=ef36c1a1aabb2ba3b0bedaaafe717bf4480be2ba8de6f3894be5fd3702b013ba
URL="https://dev-www.libreoffice.org/src/libmspub/libmspub-$VERSION.tar.xz"
PREFIX=${1:-/opt/libmspub}
HERE=$(cd "$(dirname "$0")" && pwd)

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

curl -fsSL -o "$WORK/libmspub.tar.xz" "$URL"
echo "$SHA256  $WORK/libmspub.tar.xz" | sha256sum -c -
tar -C "$WORK" -xf "$WORK/libmspub.tar.xz"
cd "$WORK/libmspub-$VERSION"
for patch in "$HERE"/patches/*.patch; do
  echo "applying $(basename "$patch")"
  patch -p1 --fuzz=0 < "$patch"
done
./configure --prefix="$PREFIX" --disable-static --disable-tools --without-docs \
  --disable-werror CXXFLAGS="-O2 -g0"
make -j"$(nproc)"
make install
