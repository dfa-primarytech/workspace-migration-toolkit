# syntax=docker/dockerfile:1

# The Publisher reader (native/pub-parser), built against the same Debian the
# app runs on, so its libmspub is the one that ships beside it. libmspub
# 0.1.4 and librevenge 0.0.5 are the versions everywhere -- neither has had a
# release since -- so this agrees with docker/publisher.Dockerfile's Ubuntu
# build and with CI. The unit tests run here: an image that exists is one
# whose reader passed them.
FROM python:3.12-slim AS publisher
RUN apt-get update \
 && apt-get install --no-install-recommends -y \
      build-essential cmake pkg-config libmspub-dev librevenge-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY native/pub-parser/CMakeLists.txt ./CMakeLists.txt
COPY native/pub-parser/src ./src
COPY native/pub-parser/tests ./tests
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
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
RUN apt-get update \
 && apt-get install --no-install-recommends -y libmspub-0.1-1 librevenge-0.0-0 \
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
