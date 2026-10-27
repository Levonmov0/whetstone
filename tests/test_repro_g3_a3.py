from pathlib import Path

import pytest

from tests.test_baseline import by_model
from tests.test_check_cli import make_suite
from whetstone.entry.cli import run


def test_baseline_that_cannot_save_its_run_keeps_the_previous_deck(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    monkeypatch.chdir(tmp_path)
    run(["check", "daily"], make_model=lambda _settings: by_model())
    deck = tmp_path / ".whetstone" / "decks" / "daily.json"
    before = deck.read_text()
    (prompt / "runs").write_text("not a folder")

    code = run(["baseline", "daily", "--models", "model-b"], make_model=lambda _settings: by_model())

    assert code == 2
    assert f"can't write the baseline run in {prompt / 'runs'}" in capsys.readouterr().err
    assert deck.read_text() == before
