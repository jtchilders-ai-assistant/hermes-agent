#!/usr/bin/env bash
#
# check-upstream-release.sh — cron monitor source for new Hermes upstream tags.
#
# Reports the active immutable release separately from source-integration refs.
# Output is stable because Hermes monitor mode hashes it between runs.
set -euo pipefail

REPO_DIR="${HERMES_FORK_DIR:-$HOME/.hermes/hermes-agent-src}"
ACTIVE_DIR="${HERMES_ACTIVE_DIR:-$HOME/.hermes/hermes-agent}"

if [ ! -d "$REPO_DIR/.git" ]; then
  echo "STATUS: source-repo-missing"
  exit 0
fi
if [ ! -d "$ACTIVE_DIR" ]; then
  echo "STATUS: active-install-missing"
  exit 0
fi

# Fetch upstream tags only; never touch branches or either working tree.
git -C "$REPO_DIR" fetch upstream --tags --prune --quiet 2>/dev/null || {
  echo "STATUS: fetch-failed (could not reach upstream remote)"
  exit 0
}

# Upstream moved from CalVer (v2026.M.D) to SemVer (v0.22.x) in Oct 2026, so
# version order alone would rank v2026.9.24 above v0.22.5. Rank stable tags by
# tag date (ties broken by version) and ignore '+canary' builds.
stable_tags() { git -C "$REPO_DIR" tag -l 'v[0-9]*' --sort=-version:refname --sort=-creatordate "$@" | grep -v '+' || true; }
LATEST="$(stable_tags | sed -n '1p')"
if [ -z "$LATEST" ]; then
  echo "STATUS: no-tags-found"
  exit 0
fi

ACTIVE_REAL="$(cd "$ACTIVE_DIR" && pwd -P)"
ACTIVE_RELEASE="$(basename "$ACTIVE_REAL")"
ACTIVE_COMMIT="$(git -C "$ACTIVE_REAL" rev-parse --short=12 HEAD 2>/dev/null || true)"
ACTIVE_VERSION="$(git -C "$ACTIVE_REAL" describe --tags --match 'v[0-9]*' --exclude '*+*' --abbrev=0 HEAD 2>/dev/null || true)"
SOURCE_BASE="$(stable_tags --points-at upstream-tag | sed -n '1p')"
[ -n "$SOURCE_BASE" ] || SOURCE_BASE="$(git -C "$REPO_DIR" rev-parse --short upstream-tag 2>/dev/null || printf unknown)"

if [ -z "$ACTIVE_COMMIT" ] || [ -z "$ACTIVE_VERSION" ]; then
  echo "STATUS: active-version-unresolved"
  echo "active_release: $ACTIVE_RELEASE"
  echo "source_base: $SOURCE_BASE"
  echo "latest_upstream: $LATEST"
  exit 0
fi

if [ "$LATEST" = "$ACTIVE_VERSION" ]; then
  STATUS=up-to-date
else
  STATUS=update-available
fi

printf 'STATUS: %s\n' "$STATUS"
printf 'active_release: %s\n' "$ACTIVE_RELEASE"
printf 'active_version: %s\n' "$ACTIVE_VERSION"
printf 'active_commit: %s\n' "$ACTIVE_COMMIT"
printf 'source_base: %s\n' "$SOURCE_BASE"
printf 'latest_upstream: %s\n' "$LATEST"
