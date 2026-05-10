# =============================================================================
# Label Printer Hub — backend container
#
# Multi-stage build:
#   1) builder       — installs Python deps into an isolated /opt/venv
#   2) runtime       — copies the venv onto a slim base, runs as UID 1000
#
# Build context: the `backend/` directory. Cache-friendly layer order: deps
# first (rare changes), source code last (frequent changes).
#
# References:
#   docs/decisions/0001-two-container-architecture.md  (two-container split)
#   docs/decisions/0002-python-fastapi-backend.md      (Python + FastAPI)
#   docs/decisions/0007-docker-image-tag-scheme.md     (multi-arch publish)
#   CLAUDE.md hard rules                               (non-root UID 1000)
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: builder
# -----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

# Reproducibility + smaller images
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

# Build tools for any deps with native extensions (Pillow, brother_ql, etc.)
# Kept tight; runtime image won't carry these.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libjpeg-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Create a fresh venv that we'll copy to the runtime stage in one go.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Stage A: deps only. Copying pyproject.toml + README first means Docker can
# reuse this layer until either of those files changes — re-running pip install
# on every source edit would be wasteful.
COPY pyproject.toml README.md ./
# Create an empty package skeleton so hatchling can resolve [project] but
# nothing app-specific is installed yet — purely a dependency-resolution pass.
RUN mkdir -p app && touch app/__init__.py \
    && pip install --upgrade pip \
    && pip install .

# Stage B: real source. Replaces the placeholder app/ and reinstalls so
# entry-points (uvicorn discovers the module via the venv) reflect the actual
# code. Without the prior layer, every code change would re-download all deps.
COPY app/ ./app/
RUN pip install --no-deps --force-reinstall .

# -----------------------------------------------------------------------------
# Stage 2: runtime
# -----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    # The internal HTTP port the backend listens on. Override at deploy time
    # to run the container on a different port without rebuilding the image.
    # The compose files in examples/ set this via the .env file.
    PORT=8000 \
    # uvicorn FORWARDED_ALLOW_IPS default — safe restriction to localhost only.
    # Deployments behind a reverse proxy (the Go frontend per ADR 0001) must
    # override this with the proxy's IP or CIDR via the FORWARDED_ALLOW_IPS
    # env var. The sample compose files set it to a docker-internal subnet.
    FORWARDED_ALLOW_IPS=127.0.0.1

# Minimal runtime deps:
# - libjpeg62-turbo, zlib1g: Pillow runtime
# - curl: HEALTHCHECK
# - tini: PID 1 signal handler so uvicorn shuts down cleanly on SIGTERM
# - ca-certificates: outbound HTTPS to Snipe-IT / Grocy / Spoolman / printer web UIs
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libjpeg62-turbo \
        zlib1g \
        curl \
        tini \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Non-root user — UID/GID 1000 per CLAUDE.md hard rule. The data volume
# will be writable by this user.
RUN groupadd --system --gid 1000 hub \
    && useradd --system --uid 1000 --gid hub --home-dir /home/hub --create-home hub \
    && mkdir -p /data \
    && chown -R hub:hub /data

# The application code is already installed into /opt/venv during the builder
# stage, so we only need to copy the venv. We do NOT copy app/ again — the
# package is importable via the venv's site-packages.
COPY --from=builder --chown=hub:hub /opt/venv /opt/venv

WORKDIR /home/hub

USER hub

# EXPOSE documents the DEFAULT port — overridden by the PORT env var at
# runtime. Adjust the `docker run -p` mapping or compose `ports` to match
# the value of PORT if you change it.
EXPOSE 8000

VOLUME ["/data"]

# Shell-form HEALTHCHECK so $PORT is expanded by the shell. Falls back to
# the ENV default of 8000 if PORT is somehow unset.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl --fail --silent --show-error "http://localhost:${PORT:-8000}/healthz" || exit 1

# tini reaps zombies and propagates SIGTERM to uvicorn cleanly. Shell-form
# CMD expands $PORT and $FORWARDED_ALLOW_IPS at start so deployments can
# change them without rebuilding the image.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port \"${PORT}\" \
    --proxy-headers \
    --forwarded-allow-ips=\"${FORWARDED_ALLOW_IPS}\" \
    --no-server-header"]
