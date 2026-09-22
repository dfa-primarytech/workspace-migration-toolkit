# Build and test image for the Publisher parser.
#
# Builds nothing but this parser: it does not run the platform service,
# does not talk to Google and holds no credentials. Point it at a .pub
# and it writes a bundle.
#
# libmspub and librevenge come from the distribution's own packages
# rather than being vendored. They are stable, LibreOffice-maintained
# C++ libraries with no reason to carry a private fork, and vendoring
# them would put a copy of someone else's MPL-2.0 source in this
# repository for no technical gain. The exact tested versions are pinned
# in docs/publisher-parser.md.
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
      libmspub-dev \
      librevenge-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY native/pub-parser/CMakeLists.txt ./CMakeLists.txt
COPY native/pub-parser/src ./src
COPY native/pub-parser/tests ./tests

RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
 && cmake --build build --parallel

# The unit tests run at build time, so an image that exists is an image
# whose adapter passed. They need no .pub file and no network.
# They are also the only check that the image's libmspub is one this
# adapter agrees with.
RUN ./build/pubir-tests

FROM ubuntu:24.04 AS runtime

# Runtime needs the shared libraries only, not the headers or a compiler.
# librevenge-0.0-0 carries librevenge, librevenge-stream and
# librevenge-generators; there is no separate stream runtime package.
RUN apt-get update \
 && apt-get install --no-install-recommends -y \
      libmspub-0.1-1 \
      librevenge-0.0-0 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=build /src/build/publisher-parser /usr/local/bin/publisher-parser

# .pub files are untrusted input from a retired application. Parse them
# as a user with no privileges and nothing to write to outside a mount.
RUN useradd --system --create-home --shell /usr/sbin/nologin parser
USER parser
WORKDIR /work

ENTRYPOINT ["/usr/local/bin/publisher-parser"]
CMD ["--help"]
