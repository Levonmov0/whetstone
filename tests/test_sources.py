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


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        (["diary", "--consented-by", "Levon", "--consented-on", "yesterday"], "consented-on must be a date like 2026-10-26"),
        (["diary", "--consented-by", " ", "--consented-on", "2026-10-26"], "consented-by is required"),
        (["a/b", "--consented-by", "Levon", "--consented-on", "2026-10-26"], "source must be a plain folder name"),
        (["..", "--consented-by", "Levon", "--consented-on", "2026-10-26"], "source must be a plain folder name"),
    ],
)
def test_add_source_refuses_bad_arguments(
    args: list[str], reason: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    monkeypatch.chdir(tmp_path)

    code = run(["add-source", "daily", *args], make_model=unused_model)

    assert code == 2
    assert reason in capsys.readouterr().err
    assert not (prompt / "cases" / "private").exists()


def test_add_source_never_overwrites_a_consent_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    monkeypatch.chdir(tmp_path)
    run(["add-source", "daily", "diary", "--consented-by", "Levon", "--consented-on", "2026-10-26"], make_model=unused_model)
    consent = prompt / "cases" / "private" / "diary" / "consent.toml"
    before = consent.read_text()

    code = run(["add-source", "daily", "diary", "--consented-by", "Hampus", "--consented-on", "2026-10-27"], make_model=unused_model)

    assert code == 2
    assert f"source diary already exists; its consent is in {consent}" in capsys.readouterr().err
    assert consent.read_text() == before
