"""Thin wrapper around git subprocess calls. Never touches the caller's
working tree — every candidate commit is checked out into its own
`git worktree`, which git guarantees is isolated from the main tree."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    pass


def _run(args: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        raise GitError("git not found on PATH — install git and make sure it's on PATH") from e
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def resolve_sha(repo: Path, ref: str) -> str:
    return _run(["rev-parse", ref], repo)


def commit_list(repo: Path, good: str, bad: str) -> list[str]:
    """Oldest -> newest commits strictly after `good`, up to and including `bad`."""
    out = _run(["rev-list", "--reverse", f"{good}..{bad}"], repo)
    return [line for line in out.splitlines() if line]


def commit_subject(repo: Path, sha: str) -> str:
    return _run(["log", "-1", "--format=%s", sha], repo)


def commit_diff(repo: Path, sha: str) -> str:
    return _run(["show", "--format=", sha], repo)


@dataclass
class Worktree:
    path: Path
    sha: str


def add_worktree(repo: Path, sha: str) -> Worktree:
    tmp_root = Path(tempfile.mkdtemp(prefix="flarebisect-"))
    wt_path = tmp_root / sha[:12]
    _run(["worktree", "add", "--detach", str(wt_path), sha], repo)
    return Worktree(path=wt_path, sha=sha)


def remove_worktree(repo: Path, wt: Worktree) -> None:
    try:
        _run(["worktree", "remove", "--force", str(wt.path)], repo)
    except GitError:
        # worktree metadata already gone; just clean the directory
        pass
    shutil.rmtree(wt.path.parent, ignore_errors=True)
