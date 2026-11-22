from typing import Any

from whetstone.features.matching.core import swipe_id


def label(grader: str = "Hampus", card: str = "d:c17", at: str = "2026-11-20T08:00:00+00:00", verdict: str = "bad", note: str = "Says HRV", reasons: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    return {"card_id": card, "case_id": card.split(":")[-1], "input": {"text": card}, "output": "Your HRV is low.", "grader": grader, "verdict": verdict, "reasons": reasons or [], "note": note, "at": at, **extra}


def test_swipe_id_is_stable_and_names_one_swipe() -> None:
    assert swipe_id(label()) == swipe_id(label(note="edited", verdict="good"))
    assert swipe_id(label()).startswith("s_")
    others = {swipe_id(label(grader="Levon")), swipe_id(label(card="d:c18")), swipe_id(label(at="2026-11-20T08:00:01+00:00"))}
    assert swipe_id(label()) not in others and len(others) == 3
