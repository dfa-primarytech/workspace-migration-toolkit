# Build and test image for the Publisher parser.
#
# Builds nothing but this parser: it does not run the platform service,
# does not talk to Google and holds no credentials. Point it at a .pub
# and it writes a bundle.
#
# librevenge comes from the distribution. libmspub 0.1.4 is built from
# LibreOffice's release tarball with this repository's small patch set
# (native/pub-parser/libmspub): it reads things it never passes on, such as
# paragraph lists. Only the patches are kept here, never libmspub's source.
# The exact tested versions are pinned in docs/publisher-parser.md.
#
# Ubuntu 24.04 rather than a Debian base so the image and the CI runner
# (ubuntu-latest) resolve the same package versions -- the parser's
# behaviour is largely libmspub's behaviour, so a version that differs
# between the container and CI would make the two disagree for reasons
# neither reports.
#
#   docker build -f docker/publisher.Dockerfile -t publisher-parser .
#   docker run --rm -v "$PWD/work:/work" publisher-parser /work/in.pub /work/out
FROM ubuntu:24.04 AS build

# build-essential and cmake for the compile; the -dev packages for the
# headers and the .pc files pkg-config reads.
RUN apt-get update \
 && apt-get install --no-install-recommends -y \
      build-essential \
      cmake \
      pkg-config \
      patch curl xz-utils ca-certificates \
      librevenge-dev libicu-dev libboost-dev zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*

COPY native/pub-parser/libmspub /libmspub
RUN sh /libmspub/build.sh /opt/libmspub
# The packages the patched library needs at run time, found from the library
# itself (ldd's /lib paths are recorded under /usr/lib by dpkg).
RUN for lib in $(ldd /opt/libmspub/lib/libmspub-0.1.so.1 | awk '/=> \//{print $3}'); do \
      dpkg -S "$lib" 2>/dev/null || dpkg -S "/usr$lib" 2>/dev/null || true; \
    done | cut -d: -f1 | sort -u \
      | grep -v -e '^libc6' -e '^libgcc' -e '^libstdc' > /opt/libmspub/runtime-packages \
 && grep -q icu /opt/libmspub/runtime-packages

WORKDIR /src
COPY native/pub-parser/CMakeLists.txt ./CMakeLists.txt
COPY native/pub-parser/src ./src
COPY native/pub-parser/tests ./tests

RUN PKG_CONFIG_PATH=/opt/libmspub/lib/pkgconfig cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
      -DPUBIR_LIBMSPUB_PATCHES="$(ls /libmspub/patches | sed 's/\.patch$//' | paste -sd, -)" \
 && cmake --build build --parallel

# The unit tests run at build time, so an image that exists is an image
# whose adapter passed. They need no .pub file and no network.
# They are also the only check that the image's libmspub is one this
# adapter agrees with.
RUN ./build/pubir-tests

FROM ubuntu:24.04 AS runtime

# Runtime needs the shared libraries only, not the headers or a compiler:
# the patched libmspub, found by the parser's run path, and the packages it
# and librevenge need. librevenge-0.0-0 carries librevenge,
# librevenge-stream and librevenge-generators.
COPY --from=build /opt/libmspub/lib /opt/libmspub/lib
COPY --from=build /opt/libmspub/runtime-packages /opt/libmspub/runtime-packages
RUN apt-get update \
 && xargs apt-get install --no-install-recommends -y librevenge-0.0-0 < /opt/libmspub/runtime-packages \
 && rm -rf /var/lib/apt/lists/*

COPY --from=build /src/build/publisher-parser /usr/local/bin/publisher-parser

# .pub files are untrusted input from a retired application. Parse them
# as a user with no privileges and nothing to write to outside a mount.
RUN useradd --system --create-home --shell /usr/sbin/nologin parser
USER parser
WORKDIR /work

ENTRYPOINT ["/usr/local/bin/publisher-parser"]
CMD ["--help"]
