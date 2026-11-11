#!/usr/bin/env bash
# Install the pinned Vale release and its two style packages into .vale/ (git-ignored), each
# verified against a SHA-256 taken from the release. No `curl | sh`, no unverified `vale sync`.
# Linux x86-64 only; elsewhere install Vale from https://github.com/errata-ai/vale/releases and
# run `vale sync`.
#
# Usage: scripts/vale_setup.sh      then run  .vale/bin/vale ...
set -euo pipefail

VALE_VERSION="3.26.0"
VALE_SHA256="22aa69a556558e4a9dfc63c17030777383d8d3c48dcdfad655fa98e839d666ed"
WRITE_GOOD_URL="https://github.com/vale-cli/write-good/releases/download/v0.4.1/write-good.zip"
WRITE_GOOD_SHA256="2960ef10861ddc7dc76292a4967eb3789bf05ca24f862042f6d15f53332887f0"
MDX_URL="https://github.com/vale-cli/MDX/releases/download/v0.3.0/MDX.zip"
MDX_SHA256="b81f2680df4015b3ed4ddd63cd17d9fc685fe022ef8c7acf3afb55f690e675ff"

root="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fetch() { # url sha256 file
  curl --fail --silent --show-error --location --retry 3 --output "$work/$3" "$1"
  echo "$2  $work/$3" | sha256sum --check --quiet - || { echo "checksum mismatch: $3" >&2; exit 1; }
}

fetch "https://github.com/errata-ai/vale/releases/download/v${VALE_VERSION}/vale_${VALE_VERSION}_Linux_64-bit.tar.gz" \
  "$VALE_SHA256" vale.tar.gz
fetch "$WRITE_GOOD_URL" "$WRITE_GOOD_SHA256" write-good.zip
fetch "$MDX_URL" "$MDX_SHA256" MDX.zip

mkdir -p "$root/.vale/bin" "$root/.vale/styles/.vale-config"
tar -xzf "$work/vale.tar.gz" -C "$root/.vale/bin" vale
rm -rf "$root/.vale/styles/write-good"
unzip -q -o "$work/write-good.zip" -d "$root/.vale/styles"
# The MDX package ships a config fragment; `vale sync` puts it where Vale reads it.
unzip -p "$work/MDX.zip" MDX/.vale.ini > "$root/.vale/styles/.vale-config/1-MDX.ini"

"$root/.vale/bin/vale" --version
