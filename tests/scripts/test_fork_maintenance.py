"""Behavioral contracts for the local patched-fork maintenance helpers."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]



def _run(command: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=check)


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "fork"
    repo.mkdir()
    _run(["git", "init", "-q"], repo)
    _run(["git", "config", "user.email", "test@example.invalid"], repo)
    _run(["git", "config", "user.name", "Test"], repo)
    (repo / "README").write_text("base\n", encoding="utf-8")
    _run(["git", "add", "README"], repo)
    _run(["git", "commit", "-qm", "base"], repo)
    scripts = repo / "scripts"
    scripts.mkdir()
    for name in ("update-fork.sh", "promote-fork.sh"):
        copied = scripts / name
        shutil.copy2(REPO_ROOT / "scripts" / name, copied)
        copied.chmod(0o755)
    _run(["git", "add", "scripts"], repo)
    _run(["git", "commit", "-qm", "add maintenance helpers"], repo)
    _run(["git", "branch", "upstream-tag"], repo)
    _run(["git", "branch", "patches"], repo)
    _run(["git", "branch", "patched-release"], repo)
    return repo


def test_update_fork_refuses_to_run_during_an_active_rebase(tmp_path):
    """A conflict recovery must continue its existing rebase, never recreate it."""
    repo = _git_repo(tmp_path)
    _run(["git", "checkout", "-qb", "topic"], repo)
    (repo / "README").write_text("topic\n", encoding="utf-8")
    _run(["git", "commit", "-am", "topic", "-q"], repo)
    _run(["git", "checkout", "-q", "patches"], repo)
    (repo / "README").write_text("patches\n", encoding="utf-8")
    _run(["git", "commit", "-am", "patches", "-q"], repo)
    assert _run(["git", "rebase", "topic"], repo, check=False).returncode != 0

    result = _run(["bash", "scripts/update-fork.sh", "v0.22.5"], repo, check=False)

    assert result.returncode != 0
    assert "rebase is in progress" in result.stderr.lower()
    assert (repo / ".git" / "rebase-merge").exists() or (repo / ".git" / "rebase-apply").exists()


def test_promote_fork_refuses_mismatched_existing_deployment_tag(tmp_path):
    """A release tag is immutable: promotion may not move refs beneath a mismatch."""
    repo = _git_repo(tmp_path)
    _run(["git", "tag", "v0.22.5"], repo)
    _run(["git", "checkout", "-qb", "integrate/v0.22.5"], repo)
    (repo / "candidate").write_text("candidate\n", encoding="utf-8")
    _run(["git", "add", "candidate"], repo)
    _run(["git", "commit", "-qm", "candidate"], repo)
    _run(["git", "checkout", "-q", "patched-release"], repo)
    _run(["git", "tag", "-a", "patched-tag/v0.22.5", "-m", "old release"], repo)

    result = _run(["bash", "scripts/promote-fork.sh", "v0.22.5"], repo, check=False)

    assert result.returncode != 0
    assert "already exists" in result.stderr
    assert _run(["git", "rev-parse", "patches"], repo).stdout == _run(
        ["git", "rev-parse", "upstream-tag"], repo
    ).stdout
