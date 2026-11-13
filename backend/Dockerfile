# =============================================================================
# Label Printer Hub — backend container
#
# Multi-stage build:
#   1) web-builder   — builds the web app from frontend/ (pnpm + Vite)
#   2) builder       — installs Python deps into an isolated /opt/venv
#   3) runtime       — copies the venv and the built web app onto a slim base,
#                      runs as UID 1000
#
# One process serves the API and the web UI (D1).
#
# Build context: the REPOSITORY ROOT (the web app lives in frontend/):
#   docker build -f backend/Dockerfile .
# Cache-friendly layer order: deps first (rare changes), source code last.
#
# WEB_SOURCE picks the stage the web app is copied from. The default is
# `web-builder` (the real Vite build); `--build-arg WEB_SOURCE=web-stub` builds
# an API-only image.
#
# References:
#   docs/decisions/0001-two-container-architecture.md  (superseded by D1)
#   docs/decisions/0002-python-fastapi-backend.md      (Python + FastAPI)
#   docs/decisions/0007-docker-image-tag-scheme.md     (multi-arch publish)
#   CLAUDE.md hard rules                               (non-root UID 1000)
# =============================================================================

ARG WEB_SOURCE=web-builder

# -----------------------------------------------------------------------------
# Stage 0a: web-builder — the Vite build of the web app
# -----------------------------------------------------------------------------
FROM node:22-bookworm-slim AS web-builder
WORKDIR /web
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
# The bundle knows the version it was built for; the hub reports its own and a mismatch reloads (#288).
ARG VERSION=0.0.0-dev
ENV HUB_VERSION="${VERSION}"
RUN pnpm build && mkdir /dist && cp -r dist/. /dist/

# -----------------------------------------------------------------------------
# Stage 0b: web-stub — empty placeholder (API-only image)
# -----------------------------------------------------------------------------
FROM scratch AS web-stub
WORKDIR /dist

# The stage the runtime image copies the web app from (see WEB_SOURCE above).
FROM ${WEB_SOURCE} AS web

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
COPY backend/pyproject.toml backend/README.md ./
# Create an empty package skeleton so hatchling can resolve [project] but
# nothing app-specific is installed yet — purely a dependency-resolution pass.
RUN mkdir -p app && touch app/__init__.py \
    && pip install --upgrade pip \
    && pip install .

# Stage B: real source. Replaces the placeholder app/ and reinstalls so
# entry-points (uvicorn discovers the module via the venv) reflect the actual
# code. Without the prior layer, every code change would re-download all deps.
COPY backend/app/ ./app/
RUN pip install --no-deps --force-reinstall .

# Licence check of what the image actually ships. Python has no lockfile, so the only
# deterministic place to judge the backend's licences is here, against the packages that
# were just installed. A violation fails the build. The policy is the repository's single
# licence-policy.yml; the script imports nothing from `app`. The tool venv holds
# pip-licenses (build-time only) and never reaches the runtime stage.
COPY licence-policy.yml /opt/licence/licence-policy.yml
COPY backend/scripts/licence_report.py /opt/licence/licence_report.py
RUN python -m venv /opt/licence-tool \
    && /opt/licence-tool/bin/pip install pip-licenses==5.5.5 \
    && /opt/licence-tool/bin/python /opt/licence/licence_report.py \
        --python /opt/venv/bin/python \
        --policy /opt/licence/licence-policy.yml

# -----------------------------------------------------------------------------
# Stage 2: runtime
# -----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# Build-time arguments — set by the CI workflow (or locally with --build-arg).
# These flow into BOTH OCI image labels (visible via `docker inspect`) AND
# runtime ENV vars (visible to the running app via os.environ).
#
# Defaults are placeholders for unattended local builds; production builds via
# .github/workflows/docker-publish.yml always pass real values.
ARG VERSION=0.0.0-dev
ARG REVISION=unknown
ARG BUILD_DATE=1970-01-01T00:00:00Z

# OCI Image Spec labels — see https://specs.opencontainers.org/image-spec/annotations/
# Visible via `docker inspect ghcr.io/strausmann/label-printer-hub-backend:VERSION`.
LABEL org.opencontainers.image.title="label-printer-hub-backend" \
      org.opencontainers.image.description="Self-hosted label printer hub for Brother PT/QL series — backend container (Python/FastAPI)" \
      org.opencontainers.image.url="https://github.com/strausmann/label-printer-hub" \
      org.opencontainers.image.source="https://github.com/strausmann/label-printer-hub" \
      org.opencontainers.image.documentation="https://github.com/strausmann/label-printer-hub/tree/main/docs" \
      org.opencontainers.image.authors="Björn Strausmann <projects@strausmann.ch>" \
      org.opencontainers.image.vendor="strausmann (independent open-source project; not affiliated with Brother Industries, Ltd.)" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.base.name="docker.io/library/python:3.12-slim-bookworm"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    # Build-info ENV vars — surfaced through the application (e.g. /healthz).
    # Set from the build ARGs above so they're baked into each image.
    HUB_VERSION="${VERSION}" \
    HUB_REVISION="${REVISION}" \
    HUB_BUILD_DATE="${BUILD_DATE}" \
    HUB_REPO_URL="https://github.com/strausmann/label-printer-hub" \
    # The internal HTTP port the backend listens on. Override at deploy time
    # to run the container on a different port without rebuilding the image.
    # The compose files in examples/ set this via the .env file.
    PORT=8000 \
    # uvicorn FORWARDED_ALLOW_IPS default — safe restriction to localhost only.
    # Deployments behind a reverse proxy must override this with the proxy's
    # single address via the FORWARDED_ALLOW_IPS env var; no subnet.
    FORWARDED_ALLOW_IPS=127.0.0.1

# Minimal runtime deps:
# - libjpeg62-turbo, zlib1g: Pillow runtime
# - curl: HEALTHCHECK
# - tini: PID 1 signal handler so uvicorn shuts down cleanly on SIGTERM
# - ca-certificates: outbound HTTPS to Snipe-IT / Grocy / Spoolman / printer web UIs
# - fonts-dejavu-core: DejaVuSans.ttf — required so ImageFont.truetype('DejaVuSans.ttf', N)
#   succeeds in label_renderer.py. Without this, Pillow falls back to load_default()
#   which is a fixed-size bitmap font that ignores the size argument — all templates
#   render identically large text regardless of font_size. Installs to:
#   /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libjpeg62-turbo \
        zlib1g \
        curl \
        tini \
        ca-certificates \
        fonts-dejavu-core \
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

# The built web app; settings.web_dist_dir defaults to this path (D1).
COPY --from=web --chown=hub:hub /dist /opt/app/web
# Licence notices for what the image redistributes (fonts and barcode reader texts are in web/licenses).
COPY --chown=hub:hub THIRD_PARTY_NOTICES.md /opt/app/THIRD_PARTY_NOTICES.md
# The project licence, also served as /licenses/agpl-3.0.txt for the About page.
COPY --chown=hub:hub LICENSE /opt/app/LICENSE
COPY --chown=hub:hub LICENSE /opt/app/web/licenses/agpl-3.0.txt

# Alembic runtime configuration and migration scripts.
#
# lifespan.py resolves alembic.ini as:
#   Path(__file__).parents[2] / "alembic.ini"
# Inside the container __file__ is the installed site-package path, so
# parents[2] = /opt/venv/lib/python3.12/site-packages — we place alembic.ini
# there. alembic.ini.runtime uses absolute script_location = /opt/migrations/alembic
# so the migration scripts are found regardless of the working directory.
COPY --chown=hub:hub backend/alembic.ini.runtime /opt/venv/lib/python3.12/site-packages/alembic.ini
COPY --chown=hub:hub backend/alembic/ /opt/migrations/alembic/

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
