import subprocess
from pathlib import Path

import pytest

from tests.test_apply_cli import git
from whetstone.platform.git import GitError, commit


pytestmark = pytest.mark.usefixtures("plain_git")


def repo_on(tmp_path: Path, branch: str) -> Path:
    """A clone whose remote's default branch is "trunk", checked out on `branch`."""
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "trunk")
    git(seed, "commit", "-q", "--allow-empty", "-m", "start")
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(tmp_path / "remote.git")], check=True)
    subprocess.run(["git", "clone", "-q", str(tmp_path / "remote.git"), str(tmp_path / "clone")], check=True)
    clone = tmp_path / "clone"
    if branch != "trunk":
        git(clone, "switch", "-q", "-c", branch)
    (clone / "file.txt").write_text("change")
    return clone


@pytest.mark.parametrize("branch", ["main", "trunk"])
def test_a_commit_to_main_or_the_default_branch_is_refused(branch: str, tmp_path: Path) -> None:
    clone = repo_on(tmp_path, branch)

    with pytest.raises(GitError, match=f"refusing to commit to {branch}"):
        commit(clone, "change", None)
    assert git(clone, "rev-list", "--count", "HEAD") == "1"
