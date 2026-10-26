import json
from pathlib import Path

import pytest

from tests.fakes import unused_model
from tests.test_agreement_cli import RUBRIC_TAIL
from tests.test_judges_cli import make_judged_suite
from whetstone.entry.cli import run
from whetstone.features.checks.core import Agreement, Side, agreement, covered_reasons
from whetstone.features.checks.load import load_judges
from whetstone.features.grading.store import load_labels


def test_a_settled_bad_after_a_good_counts_as_bad_for_the_rule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Spec item 13: "a settled: true bad by Levon after his good -> counts as bad".
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."}, 'reasons = ["assumes the outcome"]\n' + RUBRIC_TAIL)
    swipe: dict[str, object] = {"card_id": "d:x", "deck_id": "d", "case_id": "x", "input": {"text": "x"}, "output": "Did you skip it?", "caught_by": [], "note": ""}
    (prompt / "labels.jsonl").write_text(
        json.dumps({**swipe, "grader": "Levon", "verdict": "good", "reasons": [], "at": "2026-10-26T08:00:00+00:00"}) + "\n"
        + json.dumps({**swipe, "grader": "Hampus", "verdict": "bad", "reasons": ["assumes the outcome"], "at": "2026-10-26T08:01:00+00:00"}) + "\n"
    )
    monkeypatch.chdir(tmp_path)
    assert run(["settle", "daily", "d:x", "bad", "--grader", "Levon"], make_model=unused_model) == 0

    rows = agreement(load_labels(prompt), {"d:x": False}, covered_reasons({}, load_judges(prompt)))

    assert rows["Levon"] == Agreement(Side(0, 0), Side(1, 1))
