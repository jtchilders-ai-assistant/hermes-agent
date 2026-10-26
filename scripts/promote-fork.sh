#!/usr/bin/env bash
# SUPERSEDED: in-place promotion is incompatible with immutable releases.
# Kept as a fail-closed stub so old muscle memory cannot rewrite a live checkout.
set -euo pipefail
cat >&2 <<'MSG'
ERROR: scripts/promote-fork.sh is intentionally disabled.

Publishing source refs is not deployment. Follow scripts/README-fork-maintenance.md:
build a NEW immutable release with ~/.hermes/release-tools/build-parallel-release,
verify it, publish the accepted refs, and have Taylor perform the gateway
stop -> activate-<release> -> gateway start transition.
MSG
exit 64
