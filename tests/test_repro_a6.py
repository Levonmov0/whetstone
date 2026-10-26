from pathlib import Path

from whetstone.features.grading.core import disagreements
from whetstone.features.grading.store import add_label, load_labels


def label(case_id: str, grader: str, verdict: str, at: str) -> dict[str, object]:
    return {"card_id": f"d1:{case_id}", "case_id": case_id, "grader": grader, "verdict": verdict, "reasons": [], "note": "", "at": at}


def test_the_queue_is_in_first_swiped_order(tmp_path: Path) -> None:
    (tmp_path / "cases" / "private" / "diary").mkdir(parents=True)
    # The private card is swiped first, the invented one later.
    add_label(tmp_path, label("private/diary/day1", "Levon", "good", "2026-10-26T08:00:00+00:00"))
    add_label(tmp_path, label("private/diary/day1", "Hampus", "bad", "2026-10-26T08:01:00+00:00"))
    add_label(tmp_path, label("a", "Levon", "good", "2026-10-26T09:00:00+00:00"))
    add_label(tmp_path, label("a", "Hampus", "bad", "2026-10-26T09:01:00+00:00"))

    assert disagreements(load_labels(tmp_path)) == ["d1:private/diary/day1", "d1:a"]
