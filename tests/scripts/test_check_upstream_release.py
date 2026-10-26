"""Regression tests for the symlink-aware upstream release monitor."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "check-upstream-release.sh"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    marker = repo / "marker.txt"
    marker.write_text(message, encoding="utf-8")
    _git(repo, "add", "marker.txt")
    _git(
        repo,
        "-c",
        "user.name=Monitor Test",
        "-c",
        "user.email=monitor@example.invalid",
        "commit",
        "-m",
        message,
    )
    return _git(repo, "rev-parse", "HEAD")


def test_monitor_reports_active_symlink_release_not_stale_source_ref(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream.git"
    seed = tmp_path / "seed"
    source = tmp_path / "hermes-agent-src"
    release = tmp_path / "releases" / "hermes-agent" / "v2026.9.21-testsha"
    active = tmp_path / "hermes-agent"

    subprocess.run(["git", "init", "--bare", str(upstream)], check=True, capture_output=True)
    subprocess.run(["git", "init", str(seed)], check=True, capture_output=True)
    _commit(seed, "base")
    _git(seed, "tag", "v2026.8.31")
    _commit(seed, "active release")
    active_commit = _git(seed, "rev-parse", "HEAD")
    _git(seed, "tag", "v2026.9.21")
    _commit(seed, "latest release")
    _git(seed, "tag", "v2026.9.24")
    _git(seed, "remote", "add", "origin", str(upstream))
    _git(seed, "push", "origin", "HEAD", "--tags")

    subprocess.run(["git", "clone", str(upstream), str(source)], check=True, capture_output=True)
    _git(source, "remote", "rename", "origin", "upstream")
    _git(source, "branch", "upstream-tag", "v2026.8.31")

    subprocess.run(["git", "clone", str(upstream), str(release)], check=True, capture_output=True)
    _git(release, "checkout", "--detach", active_commit)
    active.symlink_to(release)

    env = os.environ.copy()
    env["HERMES_FORK_DIR"] = str(source)
    env["HERMES_ACTIVE_DIR"] = str(active)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        "STATUS: update-available",
        "active_release: v2026.9.21-testsha",
        "active_version: v2026.9.21",
        f"active_commit: {active_commit[:12]}",
        "source_base: v2026.8.31",
        "latest_upstream: v2026.9.24",
    ]


def test_monitor_ranks_semver_release_above_older_calver_and_ignores_canary(tmp_path: Path) -> None:
    """Upstream switched v2026.M.D -> v0.x; '+canary' tags are never targets."""
    upstream = tmp_path / "upstream.git"
    seed = tmp_path / "seed"
    source = tmp_path / "hermes-agent-src"
    release = tmp_path / "releases" / "hermes-agent" / "v0.22.5-testsha-r6"
    active = tmp_path / "hermes-agent"

    subprocess.run(["git", "init", "--bare", str(upstream)], check=True, capture_output=True)
    subprocess.run(["git", "init", str(seed)], check=True, capture_output=True)

    def tag_at(name: str, when: str) -> str:
        env = {**os.environ, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when}
        (seed / "marker.txt").write_text(name, encoding="utf-8")
        subprocess.run(["git", "-C", str(seed), "add", "marker.txt"], check=True, env=env)
        subprocess.run(
            ["git", "-C", str(seed), "-c", "user.name=T", "-c", "user.email=t@example.invalid",
             "commit", "-qm", name], check=True, env=env)
        subprocess.run(["git", "-C", str(seed), "-c", "user.name=T", "-c", "user.email=t@example.invalid",
                        "tag", "-a", name, "-m", name], check=True, env=env)
        return _git(seed, "rev-parse", "HEAD")

    tag_at("v2026.9.24", "2026-09-24T12:00:00Z")
    active_commit = tag_at("v0.22.5", "2026-10-23T12:00:00Z")
    tag_at("v0.22.5+canary.20261026T071310Z", "2026-10-26T12:00:00Z")
    _git(seed, "remote", "add", "origin", str(upstream))
    _git(seed, "push", "-q", "origin", "HEAD", "--tags")

    subprocess.run(["git", "clone", "-q", str(upstream), str(source)], check=True, capture_output=True)
    _git(source, "remote", "rename", "origin", "upstream")
    _git(source, "branch", "upstream-tag", "v0.22.5")
    subprocess.run(["git", "clone", "-q", str(upstream), str(release)], check=True, capture_output=True)
    _git(release, "checkout", "-q", "--detach", active_commit)
    active.symlink_to(release)

    env = {**os.environ, "HERMES_FORK_DIR": str(source), "HERMES_ACTIVE_DIR": str(active)}
    result = subprocess.run(["bash", str(SCRIPT)], env=env, check=True, capture_output=True, text=True)

    assert result.stdout.splitlines() == [
        "STATUS: up-to-date",
        "active_release: v0.22.5-testsha-r6",
        "active_version: v0.22.5",
        f"active_commit: {active_commit[:12]}",
        "source_base: v0.22.5",
        "latest_upstream: v0.22.5",
    ]
