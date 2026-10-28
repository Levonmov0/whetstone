"""The git wrapper: every git command Whetstone runs goes through here. It never pushes."""

import subprocess
from pathlib import Path


class GitError(Exception):
    pass


def _git(cwd: Path, *args: str) -> str:
    return _raw(cwd, *args).strip()


def _raw(cwd: Path, *args: str) -> str:
    """Git's output as it printed it, every byte kept."""
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError:
        raise GitError("git was not found") from None
    if done.returncode != 0:
        raise GitError(f"git {args[0]} failed: {done.stderr.strip()}")
    return done.stdout


def toplevel(path: Path) -> Path:
    """The root of the repo `path` is in."""
    return Path(_git(path, "rev-parse", "--show-toplevel")).resolve()


def head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def branch_exists(repo: Path, branch: str) -> bool:
    return bool(_git(repo, "branch", "--list", branch))


def show(repo: Path, commit: str, path: Path) -> str:
    """A file's text at `commit`; `path` is relative to the repo's root."""
    return _raw(repo, "show", f"{commit}:{path.as_posix()}")


def has_file(repo: Path, commit: str, path: Path) -> bool:
    try:
        _git(repo, "cat-file", "-e", f"{commit}:{path.as_posix()}")
    except GitError:
        return False
    return True


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
