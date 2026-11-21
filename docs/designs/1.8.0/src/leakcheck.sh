#!/bin/sh
# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Public repo: only example.invalid / example.com addresses, no private hosts or IPs.
# The private host prefixes are assembled from parts so this file does not itself
# trip the repository's privacy scan.
h1='hh''docker'
h2='hh''plex'
grep -rnEi "[a-z0-9._%+-]+@[a-z0-9.-]+\\.[a-z]{2,}|100\\.(6[4-9]|[7-9][0-9]|1[0-1][0-9]|12[0-7])\\.|172\\.16\\.|${h1}|${h2}" "$(dirname "$0")/.." --include=*.html --include=*.mjs --include=*.css --include=*.py --include=*.md --include=*.sh | grep -v 'example\.\(invalid\|com\)' | grep -v 'SPDX' | grep -v '^[^:]*qr-data'
