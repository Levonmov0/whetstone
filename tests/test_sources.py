import subprocess
import tomllib
from datetime import date
from pathlib import Path

import pytest

from tests.fakes import unused_model
from tests.test_check_cli import make_suite
from whetstone.entry.cli import run


def test_add_source_records_consent_and_ignores_itself(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    monkeypatch.chdir(tmp_path)

    code = run(["add-source", "daily", "diary", "--consented-by", "Levon", "--consented-on", "2026-10-26"], make_model=unused_model)

    source = prompt / "cases" / "private" / "diary"
    assert code == 0
    assert tomllib.loads((source / "consent.toml").read_text()) == {"consented_by": "Levon", "consented_on": date(2026, 10, 26)}
    assert (source / ".gitignore").read_text() == "*\n"


def test_a_source_is_ignored_by_git_without_a_workspace_gitignore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_suite(tmp_path, {"a": "Rest today."})
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)

    run(["add-source", "daily", "diary", "--consented-by", "Levon", "--consented-on", "2026-10-26"], make_model=unused_model)

    for path in ("prompts/daily/cases/private/diary/x.json", "prompts/daily/cases/private/diary/consent.toml"):
        assert subprocess.run(["git", "check-ignore", "-q", path], cwd=tmp_path).returncode == 0, path
