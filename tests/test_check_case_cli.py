import json
from pathlib import Path

import pytest

from tests.fakes import FakeModel
from tests.test_check_cli import make_prompt, make_workspace
from whetstone.entry.cli import run

HARNESS = (
    "import json, sys\n"
    "case = json.load(sys.stdin)\n"
    'print(json.dumps({"model": "fake-model", "system": "Be brief.", "messages": [{"role": "user", "content": case["text"]}]}))\n'
)
CHECK = 'def check(output):\n    return ["Runs long."] if "LONG" in output else []\n'


def case_prompt(workspace: Path) -> Path:
    prompt = make_prompt(make_workspace(workspace), HARNESS, {"case-0": {"text": "Rest today."}, "case-1": {"text": "Run LONG today."}})
    (prompt / "checks").mkdir()
    (prompt / "checks" / "short.py").write_text(CHECK)
    return prompt


def test_one_case_runs_alone_and_leaves_the_deck(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    case_prompt(tmp_path)
    deck = tmp_path / ".whetstone" / "decks" / "daily.json"
    deck.parent.mkdir(parents=True)
    deck.write_text('{"id": "blind", "cards": []}')
    model = FakeModel(lambda request: request["messages"][0]["content"])
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily", "--case", "case-1"], make_model=lambda _settings: model)

    assert code == 1
    assert len(model.requests) == 1
    out = capsys.readouterr().out
    assert "Run LONG today." in out
    assert "FAIL case-1: short: Runs long." in out
    assert "case-0" not in out
    assert deck.read_text() == '{"id": "blind", "cards": []}'


def test_a_tool_call_output_prints_as_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    case_prompt(tmp_path)
    (tmp_path / "prompts" / "daily" / "checks" / "short.py").unlink()
    monkeypatch.chdir(tmp_path)

    run(["check", "daily", "--case", "case-0"], make_model=lambda _settings: FakeModel(lambda _request: {"line": "Rest."}))

    assert '{\n  "line": "Rest."\n}' in capsys.readouterr().out


def test_a_proposed_case_runs_by_its_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = case_prompt(tmp_path)
    (prompt / "cases" / "proposed").mkdir()
    (prompt / "cases" / "proposed" / "new-one.json").write_text(json.dumps({"text": "A proposed day."}))
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily", "--case", "proposed/new-one"], make_model=lambda _settings: FakeModel(lambda r: r["messages"][0]["content"]))

    assert code == 0
    out = capsys.readouterr().out
    assert "A proposed day." in out and "PASS proposed/new-one" in out



@pytest.mark.parametrize("case", ["nope", "proposed/nope"])
def test_an_unknown_case_is_named(case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    case_prompt(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert run(["check", "daily", "--case", case], make_model=lambda _settings: FakeModel(lambda _r: "x")) == 2
    assert f"no case named {case}" in capsys.readouterr().err


def test_a_proposed_id_cannot_climb_out_of_proposed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = case_prompt(tmp_path)
    (prompt / "cases" / "proposed").mkdir()
    (prompt / "cases" / "private" / "diary").mkdir(parents=True)
    (prompt / "cases" / "private" / "diary" / "consent.toml").write_text('consented_by = "Levon"\nconsented_on = 2026-10-26\n')
    (prompt / "cases" / "private" / "diary" / "x.json").write_text(json.dumps({"text": "Private."}))
    model = FakeModel(lambda _r: "x")
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily", "--case", "proposed/../private/diary/x"], make_model=lambda _settings: model)

    assert code == 2
    assert model.requests == []


def test_one_case_runs_past_an_unrelated_broken_private_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = case_prompt(tmp_path)
    (prompt / "cases" / "private" / "diary").mkdir(parents=True)
    (prompt / "cases" / "private" / "diary" / "x.json").write_text("{}")  # no consent.toml
    monkeypatch.chdir(tmp_path)

    assert run(["check", "daily", "--case", "case-0"], make_model=lambda _settings: FakeModel(lambda r: r["messages"][0]["content"])) == 0
