FROM python:3.11-slim-bookworm AS scorer

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 LC_ALL=C TZ=UTC

FROM scorer AS actor

COPY pack_toolchain.sh /tmp/pack_toolchain.sh
RUN /bin/sh /tmp/pack_toolchain.sh && rm /tmp/pack_toolchain.sh

WORKDIR /work
