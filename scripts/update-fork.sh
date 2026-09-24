#!/usr/bin/env bash
# update-fork.sh — source-integration helper for the immutable-release workflow.
# It rebases the local patch stack onto an explicit upstream release tag. It
# never publishes long-lived refs, builds a release, changes the active symlink,
# or controls the gateway.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

UPSTREAM_REMOTE="upstream"
say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\n\033[1;33m!!  %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mXX  %s\033[0m\n' "$*" >&2; exit 1; }

[ "$REPO_DIR" = "$HOME/.hermes/hermes-agent-src" ] || die "Run only from ~/.hermes/hermes-agent-src"
[ ! -L "$REPO_DIR" ] || die "Source clone must not be a symlink"
[ -z "$(git status --porcelain)" ] || die "Working tree is dirty. Commit or stash first."
for ref in patches upstream-tag patched-release; do
  git rev-parse --verify "$ref" >/dev/null 2>&1 || die "Missing branch '$ref'."
done

say "Fetching $UPSTREAM_REMOTE tags"
git fetch "$UPSTREAM_REMOTE" --tags --prune

TARGET_TAG="${1:-}"
[ -n "$TARGET_TAG" ] || die "Pass an explicit upstream release tag; implicit newest-tag selection is disabled."
git rev-parse --verify "${TARGET_TAG}^{commit}" >/dev/null 2>&1 || die "Tag '$TARGET_TAG' not found."
OLD_BASE="$(git rev-parse upstream-tag)"
NEW_BASE="$(git rev-parse "${TARGET_TAG}^{commit}")"
[ "$OLD_BASE" != "$NEW_BASE" ] || { warn "upstream-tag already resolves to $TARGET_TAG"; exit 0; }

STAMP="$(date +%Y%m%d-%H%M%S)"
SNAP_TAG="pre-update/${STAMP}"
INTEG="integrate/${TARGET_TAG}"
git rev-parse --verify "$INTEG" >/dev/null 2>&1 && die "Branch '$INTEG' already exists; inspect it rather than deleting it automatically."

git tag -a "$SNAP_TAG" patches -m "patches state before update to $TARGET_TAG"
say "Created local preservation tag $SNAP_TAG; publish it before destructive ref changes"
git checkout -b "$INTEG" patches

set +e
git rebase --onto "$NEW_BASE" "$OLD_BASE" "$INTEG"
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
  warn "Rebase stopped. Resolve conflicts semantically, test, and continue with GIT_EDITOR=true git rebase --continue."
  exit "$rc"
fi

cat <<EOF

Rebase complete on $INTEG.

Next:
  1. Run range-diff, custom-footprint, targeted, adjacent, lint/import, and baseline-aware tests.
  2. Obtain independent review.
  3. Push the exact candidate with --force-with-lease and verify local == origin == GitHub SHA.
  4. Follow ~/.hermes/release-tools/docs/future-upgrade-plan.md.

Do NOT run scripts/promote-fork.sh: in-place deployment is retired.
EOF
