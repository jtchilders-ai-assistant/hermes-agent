#!/usr/bin/env bash
# SUPERSEDED: in-place promotion is incompatible with immutable releases.
set -euo pipefail
cat >&2 <<'EOF'
ERROR: scripts/promote-fork.sh is intentionally disabled.

Publishing source refs is not deployment. Follow:
  ~/.hermes/release-tools/docs/future-upgrade-plan.md
  ~/.hermes/skills/github/patched-fork-maintenance/references/rebase-validation-and-promotion.md

Build an immutable source+venv release, create and validate its allowlist
manifest, and ask Taylor to perform the offline activate-release + launchd
transition. Never modify ~/.hermes/hermes-agent or an accepted release in place.
EOF
exit 64
