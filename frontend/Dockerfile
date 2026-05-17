# =============================================================================
# Label Printer Hub — frontend container
#
# Multi-stage build:
#   0) tailwind-builder — downloads Tailwind v4 Standalone CLI, compiles CSS
#   1) builder          — Go toolchain compiles a static binary
#   2) runtime          — alpine + tini + curl + non-root UID 1000
#
# Build context: the `frontend/` directory.
#
# To vendor the Tailwind binary instead of downloading at build time (air-gapped
# CI), copy the binary to `frontend/bin/tailwindcss` and replace the download
# step with: COPY bin/tailwindcss /usr/local/bin/tailwindcss
#
# References:
#   docs/decisions/0001-two-container-architecture.md  (two-container split)
#   docs/decisions/0003-go-tailwind-htmx-pwa-frontend.md
#   docs/decisions/0007-docker-image-tag-scheme.md     (multi-arch publish)
#   CLAUDE.md hard rules                               (non-root UID 1000)
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 0: Tailwind CSS build
# -----------------------------------------------------------------------------
FROM debian:bookworm-slim AS tailwind-builder

ARG TAILWIND_VERSION=v4.1.5
ARG TARGETARCH

# Download the Tailwind v4 Standalone CLI for the current build architecture.
# The Tailwind standalone binary is a glibc ELF — debian:bookworm-slim
# provides glibc; alpine (musl) cannot execute the binary.
# TARGETARCH is set by Docker buildx: "amd64" → x64, "arm64" → arm64.
# --minify reduces the output by ~30-50% for production images.
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    ARCH_SUFFIX=$([ "$TARGETARCH" = "arm64" ] && echo "arm64" || echo "x64") && \
    curl -fsSL \
      "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-${ARCH_SUFFIX}" \
      -o /usr/local/bin/tailwindcss && \
    chmod +x /usr/local/bin/tailwindcss

WORKDIR /src

# Copy the CSS source and templates so Tailwind can scan for utility classes.
COPY web/styles/   ./web/styles/
COPY web/templates/ ./web/templates/

# Build and minify the CSS into the path the Go embed expects.
RUN tailwindcss \
      --input  web/styles/app.css \
      --output web/static/app.css \
      --minify

# -----------------------------------------------------------------------------
# Stage 1: builder
# -----------------------------------------------------------------------------
FROM golang:1.24-alpine AS builder

WORKDIR /build

# Stage A: dependency download — cached separately from source. Subsequent
# code edits don't re-resolve modules unless go.mod / go.sum change.
COPY go.mod go.sum ./
RUN go mod download

# Stage B: compile. Static binary so we don't need libc in the runtime image.
COPY . ./

# Copy the Tailwind-compiled CSS into the embed path before go build runs.
# This file is referenced by //go:embed web/static in cmd/server/main.go.
COPY --from=tailwind-builder /src/web/static/app.css ./web/static/app.css

# Build-time version metadata — set by the CI workflow.
ARG VERSION=0.0.0-dev
ARG REVISION=unknown
ARG BUILD_DATE=1970-01-01T00:00:00Z

# CGO_ENABLED=0 produces a fully static binary. -ldflags strip debug info
# and shrink the binary (~30-40% smaller). ldflags also bake version info.
RUN CGO_ENABLED=0 GOOS=linux go build \
    -trimpath \
    -ldflags="-s -w \
      -X main.version=${VERSION} \
      -X main.revision=${REVISION} \
      -X main.buildDate=${BUILD_DATE}" \
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
