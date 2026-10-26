import json
import subprocess
import tomllib
from datetime import date
from pathlib import Path

import pytest

from tests.fakes import unused_model
from tests.test_check_cli import echo_model, make_prompt, make_suite, make_workspace
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


@pytest.mark.parametrize(("path", "case_id"), [("diary/day1.json", "private/diary/day1"), ("x.json", "private/x")])
def test_a_private_case_without_consent_stops_before_the_harness(
    path: str, case_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompt = make_prompt(make_workspace(tmp_path), "import sys; print('harness ran', file=sys.stderr); sys.exit(3)", {"a": {}})
    case = prompt / "cases" / "private" / path
    case.parent.mkdir(parents=True)
    case.write_text("{}")
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model)

    err = capsys.readouterr().err
    assert code == 2
    assert f"real-data case {case_id} has no consent record; run whetstone add-source" in err
    assert "harness ran" not in err


def add_diary_case(prompt: Path) -> None:
    source = prompt / "cases" / "private" / "diary"
    source.mkdir(parents=True)
    (source / "consent.toml").write_text('consented_by = "Levon"\nconsented_on = 2026-10-26\n')
    (source / "day1.json").write_text(json.dumps({"text": "Slept badly."}))


def test_private_cases_need_repo_providers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    add_diary_case(make_suite(tmp_path, {"a": "Rest today."}))
    model = echo_model()
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: model)

    assert code == 2
    assert "whetstone.toml has no repo_providers; real-data cases need it" in capsys.readouterr().err
    assert model.requests == []


@pytest.mark.parametrize(
    ("toml", "reason"),
    [("repo_providers = [\n", "invalid TOML"), ('repo_providers = "anthropic"\n', "repo_providers must be a list of provider names")],
)
def test_a_broken_whetstone_toml_exits_2(
    toml: str, reason: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    add_diary_case(make_suite(tmp_path, {"a": "Rest today."}))
    (tmp_path / "whetstone.toml").write_text(toml)
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model)

    assert code == 2
    assert f"{tmp_path / 'whetstone.toml'}: {reason}" in capsys.readouterr().err


def private_case(prompt: Path, relative: str) -> None:
    case = prompt / "cases" / "private" / relative
    case.parent.mkdir(parents=True, exist_ok=True)
    case.write_text(json.dumps({"text": "Slept badly."}))


@pytest.mark.parametrize(
    ("consent_at", "case", "error"),
    [
        # A consent record loose in cases/private/ belongs to no source, so it covers nothing.
        ("consent.toml", "x.json", "real-data case private/x has no consent record; run whetstone add-source"),
        ("diary/consent.toml", "diary/2026/day1.json", "real-data case private/diary/2026/day1 must sit directly in its source folder, cases/private/diary/"),
    ],
)
def test_a_private_case_must_sit_directly_in_its_source(
    consent_at: str, case: str, error: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    (tmp_path / "whetstone.toml").write_text('repo_providers = ["anthropic"]\n')
    consent = prompt / "cases" / "private" / consent_at
    consent.parent.mkdir(parents=True, exist_ok=True)
    consent.write_text('consented_by = "Levon"\nconsented_on = 2026-10-26\n')
    private_case(prompt, case)
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model)

    assert code == 2
    assert error in capsys.readouterr().err


@pytest.mark.parametrize("consent", ["", 'consented_by = ""\nconsented_on = 2026-10-26\n', 'consented_by = "Levon"\nconsented_on = "soon"\n', "not = [toml"])
def test_a_consent_record_must_say_who_and_when(
    consent: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    (tmp_path / "whetstone.toml").write_text('repo_providers = ["anthropic"]\n')
    (prompt / "cases" / "private" / "diary").mkdir(parents=True)
    (prompt / "cases" / "private" / "diary" / "consent.toml").write_text(consent)
    private_case(prompt, "diary/day1.json")
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model)

    assert code == 2
    assert f"{prompt / 'cases' / 'private' / 'diary' / 'consent.toml'} must record consented_by (a name) and consented_on (a date)" in capsys.readouterr().err


def test_add_source_refuses_an_empty_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    monkeypatch.chdir(tmp_path)

    code = run(["add-source", "daily", "", "--consented-by", "Levon", "--consented-on", "2026-10-26"], make_model=unused_model)

    assert code == 2
    assert "source must be a plain folder name" in capsys.readouterr().err
    assert not (prompt / "cases" / "private").exists()
