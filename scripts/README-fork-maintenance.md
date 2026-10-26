# Fork maintenance — branch model & update workflow

This is a **personal fork** of Hermes Agent (`jtchilders-ai-assistant/hermes-agent`).
We do **not** upstream these patches and never open PRs to NousResearch.
Each cycle we rebase our patch stack onto a new upstream **release tag**, then build
a new **immutable release** from the result. Production never runs from a branch.

Host-specific build/activation details (Intel Mac mini, custom ONNX Runtime wheel,
Mnemosyne) live in the private runbook repo
`jtchilders-ai-assistant/hermes-intel-mac` (`~/workspaces/hermes-intel-mac`).

## Where things live

- Mutable source clone (rebase work happens here): `~/.hermes/hermes-agent-src`
- Immutable releases: `~/.hermes/releases/hermes-agent/<ver>-<sha7>-rN/`
- Active install: `~/.hermes/hermes-agent` → symlink to one release
- Build/activate/rollback tooling: `~/.hermes/release-tools/`

## Remotes

- `origin` = our fork, default push target. GitHub default branch = `patched-release`.
- `upstream` = `NousResearch/hermes-agent`, read-only.

## Branches (long-lived, on origin)

| Branch | Role |
|---|---|
| `upstream-tag` | Pure mirror of the upstream release tag we are based on. No custom code. |
| `patches` | Our custom commits rebased onto `upstream-tag`. `git log upstream-tag..patches` = the stack. |
| `patched-release` | Accepted source of the newest immutable release. Publishing it is **not** deployment. |

Disposable per cycle: `integrate/<tag>` (delete after acceptance).

## Tags

| Tag | Role |
|---|---|
| `patched-tag/<upstream-tag>` | Annotated; exact source of an accepted release. |
| `pre-update/<stamp>` | Snapshot of the old `patches` before a history rewrite. |

Upstream switched from CalVer (`v2026.9.24`) to SemVer (`v0.22.5`) in October 2026 and
also publishes `vX.Y.Z+canary.*` tags. The scripts pick the newest **stable** tag by
tag date and ignore `+canary`.

## Update cycle

```bash
cd ~/.hermes/hermes-agent-src

# 0. Anything new?  (also runs weekly as cron hermes-fork-upstream-release-watch)
scripts/check-upstream-release.sh

# 1. Rebase the stack onto the new tag (creates pre-update/<stamp>, stops on conflict).
scripts/update-fork.sh v0.23.0
#    On conflict: resolve semantically, git add, GIT_EDITOR=true git rebase --continue.
#    Do NOT re-run update-fork.sh after resolving.

# 2. Review the rebase.
git range-diff upstream-tag..patches v0.23.0..integrate/v0.23.0
git log --oneline v0.23.0..integrate/v0.23.0

# 3. Fork patch suites — must be green. Run them in a throwaway clone OUTSIDE ~/.hermes:
#    the test suite's home-I/O guard fails any test that touches a path under ~/.hermes
#    (including git worktree metadata and a release's site-packages).
T=~/workspaces/hermes-fork-testclone; rm -rf $T
git clone -q --no-local ~/.hermes/hermes-agent-src $T -b integrate/v0.23.0 && cd $T
export UV_FIND_LINKS=~/.hermes/release-tools/wheels     # custom Intel onnxruntime wheel
uv venv -q --python 3.14 .venv-test
uv pip install -q --python .venv-test/bin/python -e '.[anthropic]' pytest pytest-asyncio
.venv-test/bin/python -m pytest -q -o addopts= \
  tests/agent/test_auxiliary_client.py \
  tests/agent/test_anthropic_adapter.py \
  tests/agent/test_aux_progress_streaming.py \
  tests/test_trajectory_compressor.py \
  tests/agent/transports/test_developer_role_flag.py \
  tests/agent/transports/test_chat_completions.py \
  tests/gateway/test_streaming_fence_continuation.py \
  tests/tools/test_delegate_kanban_isolation.py \
  tests/scripts/test_fork_maintenance.py \
  tests/scripts/test_check_upstream_release.py
#    Confirm any failure on a clean upstream-tag checkout before blaming the stack.

# 4. Push the candidate and get an independent review.
cd ~/.hermes/hermes-agent-src
git push -u origin integrate/v0.23.0

# 5. Build + verify a NEW immutable release (hermes-intel-mac README).

# 6. After acceptance, publish refs with leases; verify local == origin == GitHub.
C=$(git rev-parse integrate/v0.23.0)
OLD_P=$(git rev-parse origin/patches); OLD_R=$(git rev-parse origin/patched-release)
OLD_U=$(git rev-parse origin/upstream-tag)
git tag -a patched-tag/v0.23.0 "$C" -m "Accepted source for release <name>"
git branch -f patches "$C"; git branch -f patched-release "$C"
git branch -f upstream-tag 'v0.23.0^{commit}'
git push origin --force-with-lease=patches:$OLD_P --force-with-lease=patched-release:$OLD_R \
  --force-with-lease=upstream-tag:$OLD_U patches patched-release upstream-tag \
  refs/tags/patched-tag/v0.23.0 refs/tags/<pre-update tag from step 1>
git push origin --delete integrate/v0.23.0 && git branch -D integrate/v0.23.0

# 7. Taylor: gateway stop -> ~/.hermes/release-tools/activate-<release> -> gateway start.
```

`scripts/promote-fork.sh` is retired and exits 64. It rewrote the live checkout in
place, which the immutable-release model forbids.

## Rollback

Runtime rollback never touches Git: Taylor stops the gateway, runs
`~/.hermes/release-tools/undo-<release>` (or `activate-release <previous>`), and starts it.
Prior source states remain in `patched-tag/*` and `pre-update/*`.

## Current custom patches

Run `git log --oneline upstream-tag..patches` for the live list. At `v0.22.5`
(`patched-tag/v0.22.5`), the stack is 10 commits:

1. `fix(auxiliary)`: keep `max_tokens` for Claude served over OpenAI-wire proxies
2. `feat(aux/compression)`: stream Claude on OpenAI-wire proxies (Argo)
3. `chore(fork)`: fork-maintenance tooling (update/promote scripts + docs)
4. `chore(fork)`: weekly upstream-release check script for cron monitor
5. `fix(providers)`: gate GPT-5 developer-role swap behind `model.disable_developer_role`
6. `fix(gateway)`: stop streaming continuation resending whole reply / inverting fences
7. `fix(fork)`: make rebased release promotion ancestry-safe
8. `fix(kanban)`: preserve worker lifecycle tools
9. `fix(fork)`: adapt proxy compatibility patches to v0.21.3 refactors
10. `fix(fork)`: fail closed on rebase and deployment-tag collisions

plus this tooling commit (immutable-release docs, SemVer-aware tag selection,
disabled `promote-fork.sh`).

The v2026.9.21 commit `[verified] fix gateway relay and tracing warnings` was dropped
at v0.22.5: its Langfuse half is moot (Langfuse removed) and the `nemo_relay` warning
is expected on Intel macOS. It is preserved in `pre-update/20261026-113255`.
