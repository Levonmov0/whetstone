import json
from pathlib import Path

import pytest

from tests.fakes import unused_model
from tests.test_check_cli import make_suite
from whetstone.entry.cli import run
from whetstone.features.checks.load import code_check_reasons


def test_a_code_check_covers_the_reasons_it_declares(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    length = prompt / "checks" / "length.py"
    length.write_text('REASONS = ["too long"]\n' + length.read_text())
    (prompt / "labels.jsonl").write_text(json.dumps({"card_id": "d:a", "case_id": "a", "grader": "Levon", "verdict": "bad", "reasons": ["too long"], "note": "", "at": "1"}) + "\n")
    monkeypatch.chdir(tmp_path)

    code = run(["reasons", "daily"], make_model=unused_model)

    assert code_check_reasons(prompt) == {"banned": [], "length": ["too long"]}
    assert (code, capsys.readouterr().out.splitlines()) == (0, ["every reason has a check"])


@pytest.mark.parametrize("declared", ['REASONS = "too long"\n', "REASONS = [len]\n", "REASONS = [\n"])
def test_a_code_check_with_unreadable_reasons_stops(declared: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    (prompt / "checks" / "length.py").write_text(declared)
    monkeypatch.chdir(tmp_path)

    code = run(["reasons", "daily"], make_model=unused_model)

    assert code == 2
    assert "check length: REASONS must be a list of text" in capsys.readouterr().err
