#!/usr/bin/env bash
#
# promote-fork.sh — promote a completed integrate/<tag> branch to production.
#
# Run this ONLY after scripts/update-fork.sh finished the rebase cleanly AND the
# custom-patch test suites are green. It:
#   1. adopts integrate/<tag> as the new 'patches'
#   2. tags the deploy: patched-tag/<tag>
#   3. resets 'patched-release' to that tested rebased commit
#   4. moves 'upstream-tag' mirror to <tag>
#   5. reinstalls the editable package into the repo venv and verifies hermes --version
#   6. pushes branches + tags to origin
#   7. deletes the disposable integrate/<tag> branch
#
# A rebase rewrites commit ancestry, so patched-release CANNOT be fast-forwarded
# to patches. Promotion therefore uses an explicit hard reset after creating a
# safety tag. This script must be run from the production checkout only after
# the Hermes gateway has been stopped; rewriting the live source under a running
# Python process can mix module versions. It does NOT delete safety tags.
#
# Usage:  scripts/promote-fork.sh v2026.9.14
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

ORIGIN_REMOTE="origin"
VENV_PY="./venv/bin/python"
VENV_PIP="./venv/bin/pip"
VENV_HERMES="./venv/bin/hermes"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mXX  %s\033[0m\n' "$*" >&2; exit 1; }

TARGET_TAG="${1:-}"
[ -n "$TARGET_TAG" ] || die "Usage: promote-fork.sh <upstream-tag>  e.g. v2026.9.14"

INTEG="integrate/${TARGET_TAG}"
git rev-parse --verify "$INTEG" >/dev/null 2>&1 || die "No branch '$INTEG'. Run update-fork.sh first."
[ -z "$(git status --porcelain)" ] || die "Working tree dirty. Resolve before promoting."
[ "$(git branch --show-current)" = "patched-release" ] \
  || die "Run promotion from the production checkout on branch 'patched-release'."

# integrate branch must actually be built on the target tag
git merge-base --is-ancestor "${TARGET_TAG}^{commit}" "$INTEG" \
  || die "$INTEG is not built on $TARGET_TAG. Aborting."

DEPLOY_TAG="patched-tag/${TARGET_TAG}"
[ "$(git rev-parse --short "$INTEG")" ] && say "Promoting $INTEG ($(git rev-parse --short "$INTEG")) -> production"

# --- 1. adopt as patches ----------------------------------------------------
say "Updating 'patches' -> $INTEG"
git branch -f patches "$INTEG"

# --- 2. deploy tag ----------------------------------------------------------
if git rev-parse --verify "$DEPLOY_TAG" >/dev/null 2>&1; then
  say "Deploy tag $DEPLOY_TAG already exists — leaving as-is"
else
  say "Tagging deploy: $DEPLOY_TAG"
  git tag -a "$DEPLOY_TAG" "$INTEG" -m "Custom patch stack rebased onto upstream $TARGET_TAG (deployed $(date +%Y-%m-%d))"
fi

# --- 3. move upstream-tag mirror -------------------------------------------
say "Moving 'upstream-tag' mirror -> $TARGET_TAG"
git branch -f upstream-tag "${TARGET_TAG}^{commit}"

# --- 4. reset patched-release to the tested, rebased stack ------------------
say "Resetting patched-release to tested patches"
git reset --hard patches

# --- 5. reinstall + verify --------------------------------------------------
say "Reinstalling editable package into repo venv"
"$VENV_PIP" install -e . --quiet
say "Verifying hermes --version"
"$VENV_HERMES" --version
say "Import smoke test of patched modules"
"$VENV_PY" - <<'PY'
import agent.auxiliary_client, agent.transports.chat_completions
import agent.anthropic_adapter, trajectory_compressor, agent.chat_completion_helpers, hermes_cli
print("OK: all patched modules import")
PY

# --- 6. push to origin ------------------------------------------------------
say "Pushing branches + tags to $ORIGIN_REMOTE"
git push -f "$ORIGIN_REMOTE" patches
git push    "$ORIGIN_REMOTE" upstream-tag patched-release
git push    "$ORIGIN_REMOTE" "$DEPLOY_TAG"
# push any pre-update/* snapshot tags created this cycle
git push    "$ORIGIN_REMOTE" --tags

# --- 7. cleanup -------------------------------------------------------------
say "Deleting disposable branch $INTEG"
git branch -D "$INTEG"

cat <<EOF

$(say "DEPLOYED: $TARGET_TAG is live on patched-release.")

Rollback if needed:
  git checkout patched-release && git reset --hard <older patched-tag/...>
  ./venv/bin/pip install -e . --quiet && ./venv/bin/hermes --version

Restart any running Hermes gateway/CLI to pick up the new code.
EOF
