#!/usr/bin/env bash
# Tell the release-tools workflow whether a change touches anything the release
# dry run depends on. Prints `true` or `false`; the workflow runs the expensive
# steps only on `true`, but the job itself always runs, so the check always reports
# (a required check skipped by a `paths:` filter never reports and blocks the PR).
#
# Usage: scripts/release_tools_scope.sh <base-sha> <head-sha>
#
# An unknown or unreachable base (new branch, force push) counts as "touched".
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <base-sha> <head-sha>" >&2
  exit 2
fi
base="$1"
head="$2"

if [[ -z "$base" || "$base" =~ ^0+$ ]] || ! git cat-file -e "${base}^{commit}" 2> /dev/null; then
  echo true
  exit 0
fi

# Read the diff into a variable first: a failing `git diff` inside a process substitution
# would not stop the script and would end as "not touched" (fail open). Any error means
# "touched", so the dry run runs.
if ! files="$(git diff --name-only --no-renames "${base}...${head}" 2> /dev/null)"; then
  echo true
  exit 0
fi

while IFS= read -r file; do
  case "$file" in
    .github/release-tools/* | .github/workflows/release-tools.yml | .releaserc.json | \
      scripts/release_dry_run.sh | scripts/release_impact.py | scripts/release_tools_scope.sh | \
      scripts/test_release_impact.py)
      echo true
      exit 0
      ;;
  esac
done <<< "$files"
echo false
