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
