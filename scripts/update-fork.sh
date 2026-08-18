#!/usr/bin/env bash
#
# update-fork.sh — periodic update of this personal Hermes fork to the latest
# upstream release TAG, carrying forward our custom patch stack.
#
# Branch model (see docs at bottom):
#   upstream-tag      pure mirror of the latest upstream release tag (no custom code)
#   patches           our custom commits, rebased onto upstream-tag  (source of truth for "what we changed")
#   patched-release   the DEPLOYED ref; ~/.hermes/hermes-agent runs this. Only ever moves to a *tested* commit.
#   integrate/<tag>   disposable per-cycle scratch branch where the rebase happens
#
# Tags:
#   patched-tag/<upstream-tag>   annotated tag per deploy, for easy rollback
#   pre-update/<something>        snapshot of the old state before a rewrite (safety net)
#
# This script automates the MECHANICAL parts (fetch, mirror, scratch branch,
# start rebase) and STOPS on the first conflict so a human (or the agent) does
# the JUDGMENT parts (conflict resolution, test review, promotion). It never
# force-pushes, never touches patched-release, and never deploys on its own.
#
# Usage:
#   scripts/update-fork.sh                 # target newest v2026.* upstream tag
#   scripts/update-fork.sh v2026.9.14      # target a specific tag
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

UPSTREAM_REMOTE="upstream"
ORIGIN_REMOTE="origin"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\n\033[1;33m!!  %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mXX  %s\033[0m\n' "$*" >&2; exit 1; }

# --- 0. preconditions -------------------------------------------------------
[ -z "$(git status --porcelain)" ] || die "Working tree is dirty. Commit/stash first."
git rev-parse --verify patches           >/dev/null 2>&1 || die "Missing branch 'patches'."
git rev-parse --verify upstream-tag      >/dev/null 2>&1 || die "Missing branch 'upstream-tag'."
git rev-parse --verify patched-release   >/dev/null 2>&1 || die "Missing branch 'patched-release'."

# --- 1. fetch upstream ------------------------------------------------------
say "Fetching $UPSTREAM_REMOTE (tags, pruned)"
git fetch "$UPSTREAM_REMOTE" --tags --prune

# --- 2. pick target tag -----------------------------------------------------
if [ "${1:-}" != "" ]; then
  TARGET_TAG="$1"
else
  TARGET_TAG="$(git tag -l 'v2026.*' --sort=-creatordate | head -1)"
fi
[ -n "$TARGET_TAG" ] || die "Could not determine target tag."
git rev-parse --verify "${TARGET_TAG}^{commit}" >/dev/null 2>&1 || die "Tag '$TARGET_TAG' not found."
say "Target upstream tag: $TARGET_TAG ($(git rev-parse --short "${TARGET_TAG}^{commit}"))"

# --- 3. what is our current base? (tip of upstream-tag) ---------------------
OLD_BASE="$(git rev-parse upstream-tag)"
say "Current base (upstream-tag tip): $(git rev-parse --short "$OLD_BASE")"

if [ "$OLD_BASE" = "$(git rev-parse "${TARGET_TAG}^{commit}")" ]; then
  warn "upstream-tag is already at $TARGET_TAG. Nothing to update. Exiting."
  exit 0
fi

# --- 4. safety snapshot of the current deployed/patch state -----------------
STAMP="$(date +%Y%m%d-%H%M%S)"
SNAP_TAG="pre-update/${STAMP}"
say "Tagging safety snapshot of current patches: $SNAP_TAG"
git tag -a "$SNAP_TAG" patches -m "patches state before update to $TARGET_TAG"

# --- 5. disposable integration branch off current patches -------------------
INTEG="integrate/${TARGET_TAG}"
git rev-parse --verify "$INTEG" >/dev/null 2>&1 && git branch -D "$INTEG"
say "Creating scratch branch $INTEG off patches"
git checkout -b "$INTEG" patches

# --- 6. rebase our stack onto the NEW tag -----------------------------------
# Replay everything that is on patches but not on the OLD base, onto the new tag.
say "Rebasing custom stack onto $TARGET_TAG"
set +e
git rebase --onto "${TARGET_TAG}^{commit}" "$OLD_BASE" "$INTEG"
RC=$?
set -e

if [ $RC -ne 0 ]; then
  cat <<EOF

$(warn "REBASE STOPPED ON A CONFLICT — human/agent action required.")

Resolve it the same way we do every cycle:
  1. git status                          # see conflicted files
  2. grep -n '^<<<<<<< \|^=======\$\|^>>>>>>> ' <file>   # find TRUE markers
  3. edit: keep BOTH sides for additive conflicts; for upstream var renames,
     use the in-scope/neighbor-consistent variable + re-add our extra args.
  4. python -c "import ast; ast.parse(open('<file>').read())"   # verify parse
  5. git add <resolved files>
  6. GIT_EDITOR=true git rebase --continue

When the rebase completes, re-run this script's TAIL steps manually, OR just
re-run:  scripts/update-fork.sh $TARGET_TAG   (it will detect the finished
rebase state is clean and continue).  Then run:

  scripts/promote-fork.sh $TARGET_TAG

EOF
  exit $RC
fi

# --- 7. rebase clean: hand off to test + promote ----------------------------
cat <<EOF

$(say "Rebase onto $TARGET_TAG completed cleanly on $INTEG.")

NEXT (not automated — these are the judgment/deploy steps):

  # a) run the custom-patch test suites — MUST be green
  ./venv/bin/python -m pytest -q \\
    tests/agent/test_auxiliary_client.py \\
    tests/agent/transports/test_chat_completions.py \\
    tests/agent/test_anthropic_adapter.py \\
    tests/test_trajectory_compressor.py \\
    tests/agent/test_cron_inline_api_call_62151.py

  # b) once green, promote:
  scripts/promote-fork.sh $TARGET_TAG

Safety snapshot of the previous patches state: $SNAP_TAG
EOF
