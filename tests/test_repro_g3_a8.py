from whetstone.features.checks.core import uncovered_reasons


def test_a_bad_swipe_with_neither_reason_nor_note_is_not_an_uncovered_reason() -> None:
    # A settle with no --note, or a reasonless bad swipe with no note, says nothing a check could stand for.
    labels = [{"card_id": "X", "grader": "Levon", "verdict": "bad", "reasons": [], "note": "", "settled": True}]

    assert uncovered_reasons(labels, covered=set()) == []
