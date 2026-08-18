#!/usr/bin/env bash
#
# check-upstream-release.sh — cron monitor source for new Hermes upstream release tags.
#
# Prints a STABLE, deterministic summary of the newest upstream release tag vs.
# the tag our fork is currently built on (branch `upstream-tag`). Designed for a
# Hermes monitor-mode cron: output is hashed each tick; identical output => no
# alert. Output only changes when a NEW upstream tag appears or our base moves,
# so you get pinged exactly once per new release, not weekly.
#
# No timestamps / no random ordering in the output (hash stability requirement).
#
set -euo pipefail

REPO_DIR="${HERMES_FORK_DIR:-$HOME/.hermes/hermes-agent}"
cd "$REPO_DIR"

# Fetch upstream tags quietly (read-only; never touches working tree/branches).
git fetch upstream --tags --prune --quiet 2>/dev/null || {
  echo "STATUS: fetch-failed (could not reach upstream remote)"
  exit 0
}

LATEST="$(git tag -l 'v2026.*' --sort=-creatordate | head -1)"
CURRENT_BASE_TAG="$(git tag -l 'v2026.*' --points-at upstream-tag --sort=-creatordate | head -1)"
# Fall back to short sha if upstream-tag isn't exactly on a v2026.* tag.
[ -n "$CURRENT_BASE_TAG" ] || CURRENT_BASE_TAG="$(git rev-parse --short upstream-tag)"

if [ -z "$LATEST" ]; then
  echo "STATUS: no-tags-found"
  exit 0
fi

if [ "$LATEST" = "$CURRENT_BASE_TAG" ]; then
  echo "STATUS: up-to-date"
  echo "current_base: $CURRENT_BASE_TAG"
  echo "latest_upstream: $LATEST"
else
  echo "STATUS: update-available"
  echo "current_base: $CURRENT_BASE_TAG"
  echo "latest_upstream: $LATEST"
fi
