"""The git wrapper: every git command Whetstone runs goes through here. It never pushes."""

import subprocess
from pathlib import Path


class GitError(Exception):
    pass


def _git(cwd: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError:
        raise GitError("git was not found") from None
    if done.returncode != 0:
        raise GitError(f"git {args[0]} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def toplevel(path: Path) -> Path:
    """The root of the repo `path` is in."""
    return Path(_git(path, "rev-parse", "--show-toplevel")).resolve()


def head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def branch_exists(repo: Path, branch: str) -> bool:
    return bool(_git(repo, "branch", "--list", branch))


def add_worktree(repo: Path, path: Path, branch: str, commit: str) -> None:
    """A new branch at `commit`, checked out at `path`; the repo's own checkout is left as it is."""
    _git(repo, "worktree", "add", "-q", "-b", branch, str(path), commit)


def commit_all(worktree: Path, message: str) -> None:
    """One commit of every change in the worktree; never on main or the remote's default branch."""
    branch = _git(worktree, "branch", "--show-current")
    try:
        default = _git(worktree, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").removeprefix("origin/")
    except GitError:
        default = None  # no remote, or one whose default branch was never fetched
    if branch in ("main", default):
        raise GitError(f"refusing to commit to {branch}")
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-q", "-m", message)


def remove_worktree(repo: Path, path: Path) -> None:
    """The worktree's folder goes; its branch stays."""
    _git(repo, "worktree", "remove", "--force", str(path))
