import json
from pathlib import Path

import pytest

from tests.test_check_cli import echo_model, make_suite
from whetstone.entry.cli import run


def test_proposed_cases_never_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    (prompt / "cases" / "proposed").mkdir()
    (prompt / "cases" / "proposed" / "b.json").write_text(json.dumps({"text": "Walk later."}))
    model = echo_model()
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: model)

    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert "PASS a" in out
    assert not any("b" in line.split() for line in out)
    assert len(model.requests) == 1


def test_a_case_that_is_not_json_stops_before_any_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    # A harness reading the case as text would accept this; the deck needs JSON.
    (prompt / "harness.py").write_text(
        "import json, sys\nprint(json.dumps({'model': 'fake-model', 'system': 'Be brief.', 'messages': [{'role': 'user', 'content': sys.stdin.read()}]}))\n"
    )
    (prompt / "cases" / "b.json").write_text("{'text': 'single quotes'}")
    model = echo_model()
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: model)

    assert code == 2
    assert "case b is not valid JSON: " in capsys.readouterr().err
    assert model.requests == []


@pytest.mark.parametrize("reasons", ['"too long"', '["too long", 3]'])
def test_reason_chips_must_be_a_list_of_text(
    reasons: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    with (prompt / "prompt.toml").open("a") as f:
        f.write(f"reasons = {reasons}\n")
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: echo_model())

    assert code == 2
    assert f'{prompt / "prompt.toml"}: reasons must be a list of text' in capsys.readouterr().err
