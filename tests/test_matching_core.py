from typing import Any

import pytest

from whetstone.features.matching.core import current, propose, swipe_id, unmatched_notes


def label(grader: str = "Hampus", card: str = "d:c17", at: str = "2026-11-20T08:00:00+00:00", verdict: str = "bad", note: str = "Says HRV", reasons: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    return {"card_id": card, "case_id": card.split(":")[-1], "input": {"text": card}, "output": "Your HRV is low.", "grader": grader, "verdict": verdict, "reasons": reasons or [], "note": note, "at": at, **extra}


def test_swipe_id_is_stable_and_names_one_swipe() -> None:
    assert swipe_id(label()) == swipe_id(label(note="edited", verdict="good"))
    assert swipe_id(label()).startswith("s_")
    others = {swipe_id(label(grader="Levon")), swipe_id(label(card="d:c18")), swipe_id(label(at="2026-11-20T08:00:01+00:00"))}
    assert swipe_id(label()) not in others and len(others) == 3


def test_unmatched_notes_are_latest_bad_swipes_with_a_note_and_no_proposal() -> None:
    wanted = label(card="d:c1")
    replaced = label(card="d:c2", note="old note")
    proposed = label(card="d:c3")
    labels = [
        wanted,
        replaced,
        label(card="d:c2", at="2026-11-20T09:00:00+00:00", verdict="good", note="fine after all"),
        proposed,
        label(card="d:c4", verdict="good", note="nice"),
        label(card="d:c5", verdict="skip", note="unsure"),
        label(card="d:c6", note=""),
        label(card="d:c7", matched_by="claude", swipe="s_x", at="2026-11-20T09:00:00+00:00"),
    ]
    events = [{"event": "proposed", "id": "m_1", "swipe": swipe_id(proposed)}]

    assert unmatched_notes(labels, events) == [wanted]


def test_current_keeps_a_matched_line_only_while_its_swipe_is_latest() -> None:
    kept = label(card="d:c1")
    kept_match = label(card="d:c1", at="2026-11-20T09:00:00+00:00", reasons=["jargon"], matched_by="claude", swipe=swipe_id(kept))
    replaced = label(card="d:c2")
    # The server's re-swipe can land before a match made from the old swipe is written.
    reswipe = label(card="d:c2", at="2026-11-20T08:30:00+00:00", verdict="good", note="")
    stale_match = label(card="d:c2", at="2026-11-20T09:00:00+00:00", reasons=["jargon"], matched_by="claude", swipe=swipe_id(replaced))
    plain = label(card="d:c3", grader="Levon")

    assert current([kept, kept_match, replaced, reswipe, stale_match, plain]) == [kept_match, reswipe, plain]


NOW = "2026-11-21T10:00:00+00:00"


@pytest.mark.parametrize(
    ("swipe", "reasons", "refusal"),
    [
        ("s_000000000000", ["jargon"], "no swipe s_000000000000"),
        ("good", ["jargon"], "not a bad swipe"),
        ("replaced", ["jargon"], "Hampus swiped d:c2 again, matching the new note instead"),
        ("bad", ["jargon", "vague"], 'no check stands for "vague"'),
        ("proposed", ["jargon"], "already matched"),
    ],
)
def test_propose_refuses(swipe: str, reasons: list[str], refusal: str) -> None:
    lines = {"bad": label(card="d:c1"), "replaced": label(card="d:c2"), "good": label(card="d:c4", verdict="good"), "proposed": label(card="d:c3")}
    labels = [*lines.values(), label(card="d:c2", at="2026-11-20T09:00:00+00:00", note="newer")]
    events = [{"event": "proposed", "id": "m_1", "swipe": swipe_id(lines["proposed"])}]
    swipe = swipe_id(lines[swipe]) if swipe in lines else swipe

    assert propose(labels, events, {"jargon"}, swipe, reasons, "why", NOW) == refusal


def test_propose_appends_an_event_and_a_matched_line_that_keeps_the_verdict() -> None:
    source = label(reasons=["generic"])
    swipe = swipe_id(source)

    event, line = propose([source], [], {"jargon", "generic", "tone"}, swipe, ["jargon", "generic", "tone"], "Quotes HRV", NOW)  # type: ignore[misc]

    match = "m_" + swipe.removeprefix("s_")
    assert event == {"event": "proposed", "id": match, "swipe": swipe, "grader": "Hampus", "card_id": "d:c17", "kind": "sure", "reasons": ["jargon", "generic", "tone"], "why": "Quotes HRV", "at": NOW}
    assert line == {**source, "reasons": ["generic", "jargon", "tone"], "matched_by": "claude", "swipe": swipe, "match": match, "counted": "sure", "at": NOW}
    assert line["verdict"] == "bad"
