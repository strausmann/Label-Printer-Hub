#!/bin/sh
# Public repo: only example.invalid / example.com addresses, no private hosts or IPs.
grep -rnEi '[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|100\.(6[4-9]|[7-9][0-9]|1[0-1][0-9]|12[0-7])\.|172\.16\.|hhdocker|hhplex' "$(dirname "$0")/.." --include=*.html --include=*.mjs --include=*.css --include=*.py --include=*.md --include=*.sh | grep -v 'example\.\(invalid\|com\)' | grep -v 'SPDX' | grep -v '^[^:]*qr-data'
