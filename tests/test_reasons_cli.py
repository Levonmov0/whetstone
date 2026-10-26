import json
from pathlib import Path

import pytest

from tests.fakes import unused_model
from tests.test_judges_cli import RUBRIC, make_judged_suite
from whetstone.entry.cli import run


def write_labels(file: Path, reasons: list[list[str]]) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    lines = [{"card_id": f"d:{i}", "case_id": str(i), "grader": "Levon", "verdict": "bad", "reasons": r, "note": "", "at": "2026-10-26T08:00:00+00:00"} for i, r in enumerate(reasons)]
    file.write_text("".join(json.dumps(line) + "\n" for line in lines))


def test_reasons_lists_what_no_check_stands_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."}, 'reasons = ["sounds unsure"]\n' + RUBRIC)
    write_labels(prompt / "labels.jsonl", [["assumes the outcome"], ["banned"], ["assumes"], ["assumes whether they did Kin's advice"], ["sounds unsure"]])
    write_labels(prompt / "cases" / "private" / "diary" / "labels.jsonl", [["assumes the outcome"]])
    monkeypatch.chdir(tmp_path)

    code = run(["reasons", "daily"], make_model=unused_model)

    assert code == 0
    assert capsys.readouterr().out.splitlines() == ["2  assumes the outcome"]


def test_reasons_with_everything_covered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    write_labels(prompt / "labels.jsonl", [["banned"]])
    monkeypatch.chdir(tmp_path)

    code = run(["reasons", "daily"], make_model=unused_model)

    assert code == 0
    assert capsys.readouterr().out.splitlines() == ["every reason has a check"]
