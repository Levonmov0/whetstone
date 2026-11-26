from pathlib import Path

import pytest


@pytest.fixture
def plain_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Git without the user's own config (signing, hooks), and with a committer."""
    (tmp_path / "gitconfig").write_text("[user]\n\tname = Tester\n\temail = tester@example.com\n[init]\n\tdefaultBranch = main\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
