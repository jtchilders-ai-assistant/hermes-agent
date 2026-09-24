# Fork maintenance under immutable Hermes releases

This personal fork carries local-only patches rebased onto explicit Nous Research release tags. Source history and runtime deployment are separate.

## Paths

- Mutable source/integration clone: `~/.hermes/hermes-agent-src`
- Stable runtime symlink: `~/.hermes/hermes-agent`
- Immutable releases: `~/.hermes/releases/hermes-agent/<tag>-<sha-prefix>`
- Release workflow: `~/.hermes/release-tools/docs/future-upgrade-plan.md`
- Operator runbook: `~/.hermes/release-tools/README.md`

Never edit, rebase, install into, or switch branches through the stable symlink or an accepted release.

## Source refs

- `upstream-tag`: selected pure upstream release.
- `patches`: complete custom stack rebased onto that tag.
- `patched-release`: accepted/published source ref; not deployment state.
- `integrate/<tag>`: disposable rebase candidate.
- `patched-tag/<tag>`: accepted-source tag.
- `pre-update/<stamp>`: preservation point before history rewrite.

## Upgrade summary

1. In this source clone, run `scripts/update-fork.sh <explicit-tag>`.
2. Resolve conflicts semantically; run range-diff, footprint checks, targeted and adjacent tests, lint/import checks, and baseline-aware wider tests.
3. Obtain independent review; push the exact candidate with lease protection; verify local = origin = GitHub SHA.
4. Build and validate a new immutable release with its own real-path venv and a pre-created allowlist manifest.
5. Publish accepted source refs with explicit expected-old SHAs. This still does not deploy.
6. Ask Taylor to boot out `user/$(id -u)/ai.hermes.gateway`, run `activate-release <release>`, and run `hermes gateway start`.
7. Verify launchd definition/process, version/SHA, integrations, plugin target, SQLite integrity, and preserved rollback.

`scripts/promote-fork.sh` is intentionally disabled because its former editable-install deployment is unsafe under this architecture.

## Rollback

Taylor boots out the same launchd service, activates the previous allowlisted release, then runs `hermes gateway start`. Do not rewrite Git refs, reinstall packages, or modify a release during incident rollback.
