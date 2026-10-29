import json
from pathlib import Path

import pytest

from tests.test_check_cli import echo_model, make_suite
from whetstone.entry.cli import run


def test_check_saves_its_outputs_as_the_deck(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_suite(tmp_path, {"a": "Rest today.", "b": "Your HRV is low."})
    monkeypatch.chdir(tmp_path)

    run(["check", "daily"], make_model=lambda _settings: echo_model())

    deck = json.loads((tmp_path / ".whetstone" / "decks" / "daily.json").read_text())
    assert deck["cards"] == [
        {"card_id": f"{deck['id']}:a", "case_id": "a", "input": {"text": "Rest today."}, "output": "Rest today.", "caught_by": []},
        {"card_id": f"{deck['id']}:b", "case_id": "b", "input": {"text": "Your HRV is low."}, "output": "Your HRV is low.", "caught_by": ["banned"]},
    ]
    assert deck["id"]
    assert (tmp_path / ".whetstone" / ".gitignore").read_text() == "*\n"


def test_a_check_that_stops_keeps_the_previous_deck(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today.", "b": "Walk later."})
    monkeypatch.chdir(tmp_path)
    run(["check", "daily"], make_model=lambda _settings: echo_model())
    deck_file = tmp_path / ".whetstone" / "decks" / "daily.json"
    before = deck_file.read_text()
    (prompt / "checks" / "banned.py").write_text("def check(output):\n    if 'Walk' in output:\n        raise ValueError('boom')\n    return []\n")

    code = run(["check", "daily"], make_model=lambda _settings: echo_model())

    assert code == 2
    assert deck_file.read_text() == before


# A harness that refuses any key it doesn't know, as a real one may.
STRICT_HARNESS = """
import json, sys
case = json.load(sys.stdin)
assert set(case) == {"text"}, sorted(case)
print(json.dumps({"model": "fake-model", "max_tokens": 50, "system": "Be brief.",
                  "messages": [{"role": "user", "content": case["text"]}]}))
"""


def test_a_case_summary_goes_on_its_card_and_never_to_the_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today.", "b": "Walk later."})
    (prompt / "harness.py").write_text(STRICT_HARNESS)
    (prompt / "cases" / "a.json").write_text(json.dumps({"text": "Rest today.", "_about": "Athlete is tired. Tests: does it say rest?"}))
    model = echo_model()
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: model)

    deck = json.loads((tmp_path / ".whetstone" / "decks" / "daily.json").read_text())
    assert code == 0
    assert [c["messages"][0]["content"] for c in model.requests] == ["Rest today.", "Walk later."]
    assert deck["cards"][0]["about"] == "Athlete is tired. Tests: does it say rest?"
    assert deck["cards"][0]["input"] == {"text": "Rest today."}
    assert "about" not in deck["cards"][1]


def test_a_case_summary_must_be_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    (prompt / "cases" / "a.json").write_text(json.dumps({"text": "Rest today.", "_about": ["tired"]}))
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: echo_model())

    assert code == 2
    assert "case a: _about must be text, the grader's summary of the case" in capsys.readouterr().err
