"""The git wrapper: every git command Whetstone runs goes through here. It never pushes."""

import subprocess
from pathlib import Path


class GitError(Exception):
    pass


def _git(cwd: Path, *args: str) -> str:
    return _raw(cwd, *args).decode().strip()


def _raw(cwd: Path, *args: str) -> bytes:
    """Git's output as it printed it, every byte kept."""
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True)
    except FileNotFoundError:
        raise GitError("git was not found") from None
    if done.returncode != 0:
        raise GitError(f"git {args[0]} failed: {done.stderr.decode(errors='replace').strip()}")
    return done.stdout  # bytes: text mode would turn \r\n into \n, and a changed file may not be text


def toplevel(path: Path) -> Path:
    """The root of the repo `path` is in."""
    return Path(_git(path, "rev-parse", "--show-toplevel")).resolve()


def head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def branch_exists(repo: Path, branch: str) -> bool:
    return bool(_git(repo, "branch", "--list", branch))


def show(repo: Path, commit: str, path: Path) -> bytes:
    """A file's bytes at `commit`; `path` is relative to the repo's root."""
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


def commit(worktree: Path, message: str, paths: list[Path] | None) -> list[str]:
    """One commit of `paths`, or of every change in the worktree when None, and the files it holds; never on main or
    the remote's default branch."""
    branch = _git(worktree, "branch", "--show-current")
    try:
        default = _git(worktree, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").removeprefix("origin/")
    except GitError:
        default = None  # no remote, or one whose default branch was never fetched
    if branch in ("main", default):
        raise GitError(f"refusing to commit to {branch}")
    _git(worktree, "add", *(["--", *map(str, paths)] if paths is not None else ["-A"]))
    _git(worktree, "commit", "-q", "-m", message)
    return _git(worktree, "show", "--name-only", "--format=", "HEAD").splitlines()


def remove_worktree(repo: Path, path: Path) -> None:
    """The worktree's folder goes; its branch stays."""
    _git(repo, "worktree", "remove", "--force", str(path))


def diff(repo: Path, base: str, tip: str) -> bytes:
    """The change from `base` to `tip` as a patch `git apply` takes."""
    return _raw(repo, "diff", "--binary", base, tip)


def changed_files(repo: Path, base: str, tip: str) -> list[str]:
    """The paths, relative to the repo's root, that `tip` adds or changes since `base`."""
    return _git(repo, "diff", "--name-only", "--diff-filter=d", base, tip).splitlines()


def delete_branch(repo: Path, branch: str) -> None:
    _git(repo, "branch", "-q", "-D", branch)
