# =============================================================================
# Label Printer Hub — frontend container
#
# Multi-stage build:
#   1) builder       — Go toolchain compiles a static binary
#   2) runtime       — alpine + tini + curl + non-root UID 1000
#
# Build context: the `frontend/` directory.
#
# Tailwind, HTMX, PWA assets and the OpenAPI-generated backend client will
# land in follow-up commits — this skeleton produces a deployable container
# that serves /healthz so the docker-publish workflow has something real to
# push at the next release.
#
# References:
#   docs/decisions/0001-two-container-architecture.md  (two-container split)
#   docs/decisions/0003-go-tailwind-htmx-pwa-frontend.md
#   docs/decisions/0007-docker-image-tag-scheme.md     (multi-arch publish)
#   CLAUDE.md hard rules                               (non-root UID 1000)
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: builder
# -----------------------------------------------------------------------------
FROM golang:1.23-alpine AS builder

WORKDIR /build

# Stage A: dependency download — cached separately from source. Subsequent
# code edits don't re-resolve modules unless go.mod / go.sum change.
COPY go.mod go.sum ./
RUN go mod download

# Stage B: compile. Static binary so we don't need libc in the runtime image.
COPY . ./
# CGO_ENABLED=0 produces a fully static binary. -ldflags strip debug info
# and shrink the binary (~30-40% smaller).
RUN CGO_ENABLED=0 GOOS=linux go build \
    -trimpath \
    -ldflags="-s -w" \
    -o /out/server \
    ./cmd/server

# -----------------------------------------------------------------------------
# Stage 2: runtime
# -----------------------------------------------------------------------------
FROM alpine:3.20 AS runtime

# Build-time arguments — set by the CI workflow (.github/workflows/docker-publish.yml).
# Local builds without --build-arg get the placeholder defaults below.
ARG VERSION=0.0.0-dev
ARG REVISION=unknown
ARG BUILD_DATE=1970-01-01T00:00:00Z

# OCI image labels — visible via `docker inspect`. Keep in sync with the
# backend Dockerfile so both images describe themselves identically.
LABEL org.opencontainers.image.title="label-printer-hub-frontend" \
      org.opencontainers.image.description="Self-hosted label printer hub for Brother PT/QL series — frontend container (Go + Tailwind + HTMX + PWA)" \
      org.opencontainers.image.url="https://github.com/strausmann/label-printer-hub" \
      org.opencontainers.image.source="https://github.com/strausmann/label-printer-hub" \
      org.opencontainers.image.documentation="https://github.com/strausmann/label-printer-hub/tree/main/docs" \
      org.opencontainers.image.authors="Björn Strausmann <strausmannservices@googlemail.com>" \
      org.opencontainers.image.vendor="strausmann (independent open-source project; not affiliated with Brother Industries, Ltd.)" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.base.name="docker.io/library/alpine:3.20"

ENV PORT=8080 \
    BACKEND_URL=http://backend:8000 \
    HUB_VERSION="${VERSION}" \
    HUB_REVISION="${REVISION}" \
    HUB_BUILD_DATE="${BUILD_DATE}" \
    HUB_REPO_URL="https://github.com/strausmann/label-printer-hub"

# Runtime essentials:
#   tini             — PID 1 signal handler so SIGTERM propagates cleanly
#   curl             — HEALTHCHECK probe
#   ca-certificates  — outbound HTTPS to the backend (when proxying SSE/API)
# Then create the non-root user (UID 1000, matches the backend container).
RUN apk add --no-cache tini curl ca-certificates \
    && addgroup -S -g 1000 hub \
    && adduser -S -u 1000 -G hub -s /sbin/nologin -h /home/hub hub

# Copy the compiled binary from the builder. No source code, no Go toolchain
# in the runtime image.
COPY --from=builder --chown=hub:hub /out/server /usr/local/bin/server

USER hub
WORKDIR /home/hub

# EXPOSE documents the DEFAULT port — overridden by the PORT env var at
# runtime. Adjust the `docker run -p` mapping or compose `ports` to match
# the value of PORT if you change it.
EXPOSE 8080

# Shell-form HEALTHCHECK so $PORT is expanded by the shell.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl --fail --silent --show-error "http://localhost:${PORT:-8080}/healthz" || exit 1

# tini reaps zombies and propagates SIGTERM cleanly. The Go server reads $PORT
# from the environment itself, so we don't need a shell wrapper around it.
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/server"]
