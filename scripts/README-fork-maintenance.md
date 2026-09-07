# Fork maintenance — branch model & update workflow

This is a **personal fork** of Hermes Agent. We do **not** upstream changes.
We periodically pull the latest upstream **release tag** and replay our custom
patches on top of it, then deploy the result to `~/.hermes/hermes-agent` (which
runs from the `patched-release` branch).

## Branches (long-lived)

| Branch | Role |
|---|---|
| `upstream-tag` | Pure mirror of the latest upstream release **tag**. No custom code, ever. |
| `patches` | Our custom commits, rebased onto `upstream-tag`. Source of truth for "what we changed". `git diff upstream-tag..patches` = our exact footprint. |
| `patched-release` | The **deployed** ref. `~/.hermes/hermes-agent` checks this out. Only ever fast-forwarded to a *tested* commit. |

Disposable per-cycle: `integrate/<tag>` (rebase happens here, deleted after promote).

## Tags

| Tag | Role |
|---|---|
| `patched-tag/<upstream-tag>` | One annotated tag per deploy. Rollback target. |
| `pre-update/<...>` | Snapshot of the previous state before a history-rewriting update. Safety net. |

## Remotes

- `origin` = our fork (`jtchilders-ai-assistant/hermes-agent`), default push target. Default branch on GitHub = `patched-release`.
- `upstream` = `NousResearch/hermes-agent`, read-only, pull updates from here.

## Update workflow (each cycle)

```bash
cd ~/.hermes/hermes-agent

# 1. Rebase our stack onto the newest upstream tag (stops on first conflict).
scripts/update-fork.sh                 # or: scripts/update-fork.sh v2026.9.14

#    If it stops on a conflict, resolve (keep-both for additive; in-scope var
#    for upstream renames), then:  GIT_EDITOR=true git rebase --continue

# 2. Run the custom-patch test suites — MUST be green:
./venv/bin/python -m pytest -q \
  tests/agent/test_auxiliary_client.py \
  tests/agent/transports/test_chat_completions.py \
  tests/agent/test_anthropic_adapter.py \
  tests/test_trajectory_compressor.py \
  tests/agent/test_cron_inline_api_call_62151.py

# 3. Promote to production (adopts patches, tags, resets patched-release to
#    the tested rebased stack, reinstalls venv, verifies hermes --version,
#    pushes). Stop the running gateway before this step.
scripts/promote-fork.sh v2026.9.14

# 4. Restart any running Hermes gateway/CLI to pick up the new code.
```

## Rollback

```bash
git checkout patched-release
git reset --hard patched-tag/<older-version>
./venv/bin/pip install -e . --quiet && ./venv/bin/hermes --version
```

## Our current custom patches (the `patches` stack)

Run `git log --oneline upstream-tag..patches` for the live list. As of the
first cycle (upstream `v2026.8.16`):

1. `fix(auxiliary): keep max_tokens for Claude served over OpenAI-wire proxies`
2. `feat(transports): config-gated strip of 'name' on tool-result messages`
3. `feat(aux/compression): stream Claude on OpenAI-wire proxies (Argo)`
4. `fix(cron): stream Claude-over-proxy inline so cron does not hit 'streaming required'`

All are ALCF/Argo-specific and gated behind config flags
(`strip_tool_message_name`, `stream_claude_on_proxy`). None exist upstream.
