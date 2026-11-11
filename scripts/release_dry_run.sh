#!/usr/bin/env bash
# Compute the version semantic-release would release for a commit message, without
# publishing anything. Everything happens in a throw-away git repository with a local
# bare repository as its "remote"; no network, no token, no tag leaves the temp dir.
#
# Usage:
#   scripts/release_dry_run.sh "<commit message>"   print the next version, or "none"
#   scripts/release_dry_run.sh --notes "<message>"  print the generated release notes
#   scripts/release_dry_run.sh --all                run every sample message of
#                                                   scripts/test_release_impact.py and compare
#                                                   with release_impact.py (exit 1 on a difference)
#
# Needs: `npm ci --ignore-scripts` in .github/release-tools, python3, git.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SR="$ROOT/.github/release-tools/node_modules/.bin/semantic-release"

if [[ ! -x "$SR" ]]; then
  echo "semantic-release not installed: run 'npm ci --ignore-scripts' in .github/release-tools" >&2
  exit 2
fi

# The temp dir goes away on every exit path, including errors and signals.
TMP_DIR=""
trap '[[ -z "$TMP_DIR" ]] || rm -rf "$TMP_DIR"' EXIT
trap 'exit 130' INT TERM

# Run one dry run. $1 = mode (version|notes), $2 = commit message.
dry_run() {
  local mode="$1" message="$2" tmp
  tmp="$(mktemp -d)"
  TMP_DIR="$tmp"
  # Never inherit CI or token variables: this must not be able to publish.
  local -a clean_env=(env -u GITHUB_TOKEN -u GH_TOKEN -u NPM_TOKEN -u GITHUB_REPOSITORY -u GITHUB_ACTIONS -u CI
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null)
  (
    set -euo pipefail
    cd "$tmp"
    git init -q --bare -b main remote.git
    git init -q -b main work
    cd work
    git config user.name "Dry Run"
    git config user.email "dry-run@example.invalid"
    git config commit.gpgsign false
    git remote add origin "file://$tmp/remote.git"
    git commit -q --allow-empty -m "chore: initial"
    git tag v1.0.0
    printf '%s\n' "$message" | git commit -q --allow-empty --allow-empty-message --cleanup=verbatim -F -
    git push -q origin main
    python3 - "$ROOT/.releaserc.json" "$tmp/remote.git" "$mode" > .releaserc.json <<'PY'
import json, sys
path, remote, mode = sys.argv[1:4]
with open(path, encoding="utf-8") as fh:
    cfg = json.load(fh)
keep = ["@semantic-release/commit-analyzer"]
if mode == "notes":
    keep.append("@semantic-release/release-notes-generator")
cfg["plugins"] = [p for p in cfg["plugins"] if (p[0] if isinstance(p, list) else p) in keep]
cfg["repositoryUrl"] = "file://" + remote
cfg["branches"] = ["main"]
json.dump(cfg, sys.stdout, indent=2)
PY
    "${clean_env[@]}" "$SR" --dry-run --no-ci 2>&1
  ) > "$tmp/out.log" || { cat "$tmp/out.log" >&2; return 1; }
  if [[ "$mode" == "notes" ]]; then
    sed -n '/Release note for version/,$p' "$tmp/out.log"
  elif grep -q 'The next release version is' "$tmp/out.log"; then
    sed -n 's/.*The next release version is \([0-9][0-9.]*\).*/\1/p' "$tmp/out.log" | head -1
  else
    echo none
  fi
}

if [[ $# -eq 0 ]]; then
  echo "usage: $0 [--notes] \"<commit message>\" | --all" >&2
  exit 2
fi

case "$1" in
  --notes) dry_run notes "${2:?commit message required}" ;;
  --all)
    exec python3 - "$ROOT" <<'PY'
import subprocess, sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "scripts"))
import release_impact as ri
import test_release_impact as t

rules = ri.load_release_rules()
diffs, ran = [], 0
for message in t.sample_messages():
    impact = ri.commit_impact(ri.parse_commit(message, "0123456789abcdef"), rules)
    expected = ri.bump("1.0.0", impact) or "none"
    got = subprocess.run(
        [str(root / "scripts" / "release_dry_run.sh"), message],
        check=True, stdout=subprocess.PIPE, text=True,
    ).stdout.strip()
    ran += 1
    if got != expected:
        diffs.append((message, expected, got))
print(f"ran {ran} sample messages, {len(diffs)} differences")
for message, expected, got in diffs:
    print(f"DIFF {message!r}: release_impact says {expected}, semantic-release says {got}")
sys.exit(1 if diffs else 0)
PY
    ;;
  *) dry_run version "$1" ;;
esac
