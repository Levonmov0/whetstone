import json
from pathlib import Path

import pytest

from whetstone.features.baseline.core import baseline_verdict, swipe_tally
from whetstone.features.grading.store import load_labels


def passes(*passing: str, cases: str = "abc") -> dict[str, bool]:
    return {case: case in passing for case in cases}


@pytest.mark.parametrize(
    ("results", "verdict"),
    [
        ({"fake-model": passes(), "model-b": passes("a", "b")},
         "Yes: a model change alone fixes most failures. model-b passes 2 of the 3 cases fake-model fails."),
        ({"fake-model": passes(), "model-b": passes("a")},
         "No: no listed model fixes most failures. The best, model-b, passes 1 of the 3 cases fake-model fails. The prompt is the problem."),
        ({"fake-model": passes("a", "b", "c"), "model-b": passes()},
         "fake-model passes every check on every case; a model change has nothing to fix."),
        ({"fake-model": passes("d", cases="abcd"), "model-b": passes("a", "b", cases="abcd")},
         "Yes: a model change alone fixes most failures. model-b passes 2 of the 3 cases fake-model fails. It fails 1 case fake-model passes."),
        ({"fake-model": passes(), "model-b": passes("a"), "model-c": passes("a", "b", "c")},
         "Yes: a model change alone fixes most failures. model-c passes 3 of the 3 cases fake-model fails."),
    ],
)
def test_baseline_verdict(results: dict[str, dict[str, bool]], verdict: str) -> None:
    assert baseline_verdict(results) == verdict


def test_swipe_tally_counts_a_graders_swipe_never_claudes_matched_line(tmp_path: Path) -> None:
    old = {"card_id": "d:a:prod", "case_id": "a", "grader": "Hampus", "verdict": "bad", "at": "2026-11-20T08:00:00+00:00"}
    reswipe = {**old, "verdict": "good", "at": "2026-11-20T09:00:00+00:00"}
    late_match = {**old, "matched_by": "claude", "swipe": "s_x", "at": "2026-11-20T09:00:01+00:00"}
    (tmp_path / "labels.jsonl").write_text("".join(json.dumps(line) + "\n" for line in [old, reswipe, late_match]))

    assert swipe_tally(load_labels(tmp_path), "d", {"prod": "m"}) == {"m": {"good": 1, "bad": 0, "skip": 0}}
