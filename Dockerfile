# syntax=docker/dockerfile:1

# The Publisher reader (native/pub-parser), built against the same Debian the
# app runs on. libmspub 0.1.4 is built from LibreOffice's release tarball with
# this repository's patches (native/pub-parser/libmspub: it reads things it
# never passes on, such as paragraph lists), into /opt/libmspub. The reader
# links to that copy by its run path. The unit tests run here: an image that
# exists is one whose reader passed them.
FROM python:3.12-slim AS publisher
RUN apt-get update \
 && apt-get install --no-install-recommends -y \
      build-essential cmake pkg-config patch curl xz-utils ca-certificates \
      librevenge-dev libicu-dev libboost-dev zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*
COPY native/pub-parser/libmspub /libmspub
RUN sh /libmspub/build.sh /opt/libmspub
# The Debian packages the patched library needs at run time, found from the
# library itself (ldd's /lib paths are recorded under /usr/lib by dpkg).
RUN for lib in $(ldd /opt/libmspub/lib/libmspub-0.1.so.1 | awk '/=> \//{print $3}'); do \
      dpkg -S "$lib" 2>/dev/null || dpkg -S "/usr$lib" 2>/dev/null || true; \
    done | cut -d: -f1 | sort -u \
      | grep -v -e '^libc6$' -e '^libgcc' -e '^libstdc' > /opt/libmspub/runtime-packages \
 && grep -q icu /opt/libmspub/runtime-packages
WORKDIR /src
COPY native/pub-parser/CMakeLists.txt ./CMakeLists.txt
COPY native/pub-parser/src ./src
COPY native/pub-parser/tests ./tests
RUN PKG_CONFIG_PATH=/opt/libmspub/lib/pkgconfig cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
      -DPUBIR_LIBMSPUB_PATCHES="$(ls /libmspub/patches | sed 's/\.patch$//' | paste -sd, -)" \
 && cmake --build build --parallel \
 && ./build/pubir-tests

FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.lock pyproject.toml README.md LICENSE ./
COPY app ./app
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.lock \
    && python -m pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
# Runtime libraries for the Publisher reader only: no headers, no compiler.
# The patched libmspub, and the packages it and librevenge need.
COPY --from=publisher /opt/libmspub/lib /opt/libmspub/lib
COPY --from=publisher /opt/libmspub/runtime-packages /opt/libmspub/runtime-packages
RUN apt-get update \
 && xargs apt-get install --no-install-recommends -y librevenge-0.0-0 < /opt/libmspub/runtime-packages \
 && rm -rf /var/lib/apt/lists/*
COPY --from=publisher /src/build/publisher-parser /usr/local/bin/publisher-parser
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels workspace-migration-toolkit \
    && rm -rf /wheels \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app \
    && publisher-parser --version
USER 10001:10001
EXPOSE 8080
CMD ["workspace-server"]
