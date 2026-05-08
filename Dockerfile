# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────
# Synthadoc — multi-stage image
#
# Targets
#   base    (default) — all core skills, no vector search
#   vectors            — adds fastembed (requires Rust build)
#
# Build args
#   PYTHON_VERSION  defaults to 3.11
# ─────────────────────────────────────────────────────────

ARG PYTHON_VERSION=3.11

# ── Stage 1: build wheels ──────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY pyproject.toml ./
COPY synthadoc/__init__.py synthadoc/__init__.py
COPY VERSION ./

RUN pip install --upgrade pip hatchling && \
    pip wheel --no-cache-dir --wheel-dir /wheels .

# ── Stage 2: vectors builder (optional target) ─────────────
FROM builder AS vectors-builder

RUN curl https://sh.rustup.rs -sSf | sh -s -- -y --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}"

RUN pip wheel --no-cache-dir --wheel-dir /wheels ".[vectors]"

# ── Stage 3: base runtime ─────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS base

LABEL org.opencontainers.image.source="https://github.com/axoviq-ai/synthadoc"
LABEL org.opencontainers.image.description="Synthadoc — domain-agnostic LLM wiki compilation engine"
LABEL org.opencontainers.image.licenses="AGPL-3.0-or-later"

RUN apt-get update && apt-get install -y --no-install-recommends \
        libffi8 \
        libssl3 \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1001 synthadoc && \
    useradd --uid 1001 --gid synthadoc --no-create-home synthadoc

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links /wheels synthadoc && \
    rm -rf /wheels

COPY synthadoc/ synthadoc/
COPY hooks/ hooks/
COPY VERSION ./

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN mkdir -p /wikis && chown synthadoc:synthadoc /wikis

RUN mkdir -p /home/synthadoc/.synthadoc && \
    chown -R synthadoc:synthadoc /home/synthadoc
ENV HOME=/home/synthadoc

VOLUME ["/wikis"]

EXPOSE 7070

USER synthadoc

ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]

# ── Stage 4: vectors runtime ───────────────────────────────
FROM base AS vectors

USER root
COPY --from=vectors-builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links /wheels "synthadoc[vectors]" && \
    rm -rf /wheels

USER synthadoc

LABEL org.opencontainers.image.description="Synthadoc — with fastembed vector search"
