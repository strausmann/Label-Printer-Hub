# =============================================================================
# Label Printer Hub — backend container
#
# Multi-stage build:
#   1) builder       — installs Python deps into an isolated /opt/venv
#   2) runtime       — copies the venv + app onto a slim base, runs as UID 1000
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
# Keep the list tight; runtime image won't carry these.
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

# Install the project. Copying pyproject.toml first lets the layer cache
# kick in when only app code changes (deps stay unchanged).
COPY pyproject.toml ./
COPY app/ ./app/
RUN pip install --upgrade pip \
    && pip install .

# -----------------------------------------------------------------------------
# Stage 2: runtime
# -----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    PORT=8000

# Minimal runtime deps:
# - libjpeg62-turbo, zlib1g: Pillow runtime
# - curl: healthcheck (alternative would be wget; curl is more diagnostic-friendly)
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

# Bring the venv + app source from the builder.
COPY --from=builder --chown=hub:hub /opt/venv /opt/venv
COPY --chown=hub:hub app/ /app/app/

WORKDIR /app

USER hub

EXPOSE 8000

VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl --fail --silent --show-error http://localhost:8000/healthz || exit 1

# tini reaps zombies and propagates SIGTERM to uvicorn cleanly.
# --proxy-headers + --forwarded-allow-ips='*' so we get correct client IPs
# behind the Go frontend (which proxies / and /api/*).
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips=*", \
     "--no-server-header"]
