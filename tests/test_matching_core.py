from typing import Any

import pytest

from whetstone.features.matching.core import Refusal, answer, answer_problem, current, evidence, idea_lines, kept_and_waiting, pending, propose, sure_items, swipe_id, undo, undone_count, unmatched_notes


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
    events = [asked(proposed, ["jargon"])]

    assert unmatched_notes(labels, events, {"jargon"}) == [wanted]


def test_current_keeps_a_matched_line_only_while_its_swipe_is_latest() -> None:
    kept = label(card="d:c1")
    kept_match = label(card="d:c1", at="2026-11-20T09:00:00+00:00", reasons=["jargon"], matched_by="claude", swipe=swipe_id(kept))
    replaced = label(card="d:c2")
    # The server's re-swipe can land before a match made from the old swipe is written.
    reswipe = label(card="d:c2", at="2026-11-20T08:30:00+00:00", verdict="good", note="")
    stale_match = label(card="d:c2", at="2026-11-20T09:00:00+00:00", reasons=["jargon"], matched_by="claude", swipe=swipe_id(replaced))
    plain = label(card="d:c3", grader="Levon")

    assert current([kept, kept_match, replaced, reswipe, stale_match, plain]) == [kept_match, reswipe, plain]


def test_current_skips_a_matched_line_its_grader_never_swiped() -> None:
    swipe = label()
    # A settle written before settling stopped copying Claude's match fields: Levon's, made from Hampus's swipe.
    old_settle = label(grader="Levon", verdict="good", at="2026-11-20T09:00:00+00:00", settled=True, matched_by="claude", swipe=swipe_id(swipe))

    assert current([swipe, old_settle]) == [swipe]


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
    events = [asked(lines["proposed"], ["jargon"])]
    swipe = swipe_id(lines[swipe]) if swipe in lines else swipe

    result = propose(labels, events, {"jargon"}, swipe, reasons, "why", NOW, "sure")
    assert isinstance(result, Refusal) and result.message == refusal


def test_propose_appends_an_event_and_a_matched_line_that_keeps_the_verdict() -> None:
    source = label(reasons=["generic"])
    swipe = swipe_id(source)

    proposal = propose([source], [], {"jargon", "generic", "tone"}, swipe, ["jargon", "generic", "tone"], "Quotes HRV", NOW, "sure")

    assert not isinstance(proposal, Refusal)
    event, line = proposal

    match = "m_" + swipe.removeprefix("s_")
    assert event == {"event": "proposed", "id": match, "swipe": swipe, "grader": "Hampus", "card_id": "d:c17", "kind": "sure", "reasons": ["jargon", "generic", "tone"], "why": "Quotes HRV", "at": NOW}
    assert line == {**source, "reasons": ["generic", "jargon", "tone"], "matched_by": "claude", "swipe": swipe, "match": match, "counted": "sure", "at": NOW}
    assert line is not None and line["verdict"] == "bad"


def test_evidence_splits_counted_bad_swipes_into_tapped_claude_sure_and_confirmed() -> None:
    tapped = label(card="d:c1", reasons=["jargon"])
    noted = label(card="d:c2")
    confirmed = label(card="d:c6")
    already_tapped = label(card="d:c3", reasons=["jargon"])
    labels = [
        tapped,
        noted,
        label(card="d:c2", at=NOW, reasons=["jargon"], matched_by="claude", swipe=swipe_id(noted), counted="sure"),
        already_tapped,
        label(card="d:c3", at=NOW, reasons=["jargon", "tone"], matched_by="claude", swipe=swipe_id(already_tapped)),
        label(card="d:c4", reasons=["tone"]),
        label(card="d:c5", verdict="good", reasons=["jargon"]),
        confirmed,
        label(card="d:c6", at=NOW, reasons=["biometric jargon"], matched_by="claude", swipe=swipe_id(confirmed), counted="confirmed"),
    ]

    assert evidence(labels, {"jargon", "biometric jargon"}) == (2, 1, 1)


def test_an_ask_proposal_waits_for_the_grader_and_writes_no_line() -> None:
    source = label()
    swipe = swipe_id(source)

    proposal = propose([source], [], {"jargon"}, swipe, ["jargon"], "Sounds like jargon", NOW, kind="ask")

    assert proposal == ({"event": "proposed", "id": "m_" + swipe.removeprefix("s_"), "swipe": swipe, "grader": "Hampus", "card_id": "d:c17", "kind": "ask", "reasons": ["jargon"], "why": "Sounds like jargon", "at": NOW}, None)


def asked(source: dict[str, Any], reasons: list[str], kind: str = "ask", why: str = "Sounds like it") -> dict[str, Any]:
    swipe = swipe_id(source)
    return {"event": "proposed", "id": "m_" + swipe.removeprefix("s_"), "swipe": swipe, "grader": source["grader"], "card_id": source["card_id"], "kind": kind, "reasons": reasons, "why": why, "at": NOW}


def test_pending_lists_the_graders_unanswered_asks_with_reasons_still_covered() -> None:
    waiting = label(card="d:c1", note="Feels like a horoscope", output="Today is a chance to reset.")
    other_grader = label(card="d:c1", grader="Levon")
    sure = label(card="d:c2")
    answered = label(card="d:c3")
    labels = [waiting, other_grader, sure, answered]
    events = [asked(waiting, ["generic", "deleted judge"], why="Could be anyone's"), asked(other_grader, ["generic"]), asked(sure, ["generic"], kind="sure"), asked(answered, ["generic"]),
              {"event": "answered", "id": asked(answered, [])["id"], "answer": "no", "at": NOW}]

    assert pending(labels, events, {"generic"}, "Hampus") == [
        {"id": asked(waiting, [])["id"], "card_id": "d:c1", "note": "Feels like a horoscope", "excerpt": "Today is a chance to reset.", "reasons": ["generic"], "why": "Could be anyone's"},
    ]


def test_a_replaced_swipe_or_a_dead_reason_makes_an_item_stale() -> None:
    replaced = label(card="d:c1")
    reswipe = label(card="d:c1", at=NOW, note="Still too vague")
    dead = label(card="d:c2")
    dead_sure = label(card="d:c3")
    dead_no = label(card="d:c4")
    labels = [replaced, reswipe, dead, dead_sure, dead_no]
    events = [asked(replaced, ["generic"]), asked(dead, ["deleted judge"]), asked(dead_sure, ["deleted judge"], kind="sure"), asked(dead_no, ["deleted judge"]),
              {"event": "answered", "id": asked(dead_no, [])["id"], "answer": "no", "at": NOW}]

    assert pending(labels, events, {"generic"}, "Hampus") == []
    assert unmatched_notes(labels, events, {"generic"}) == [reswipe, dead, dead_sure]
    proposal = propose(labels, events, {"generic"}, swipe_id(dead), ["generic"], "Could be anyone's", NOW, kind="ask")
    assert not isinstance(proposal, Refusal)
    assert proposal[0]["id"] == "m_" + swipe_id(dead).removeprefix("s_") + "_2"


def test_yes_counts_the_suggested_reasons_still_covered_as_confirmed() -> None:
    source = label(reasons=["tone"])
    item = asked(source, ["generic", "deleted judge"])

    writes = answer([source], [item], {"generic", "tone"}, "Hampus", item["id"], "yes", None, NOW)

    assert writes == (
        {"event": "answered", "id": item["id"], "answer": "yes", "at": NOW},
        {**source, "reasons": ["tone", "generic"], "matched_by": "claude", "swipe": swipe_id(source), "match": item["id"], "counted": "confirmed", "at": NOW},
    )


def test_different_counts_only_the_picked_reason_and_no_counts_nothing() -> None:
    source = label(reasons=["tone"])
    item = asked(source, ["generic"])

    different = answer([source], [item], {"generic", "tone", "jargon"}, "Hampus", item["id"], "different", "jargon", NOW)
    no = answer([source], [item], {"generic", "tone"}, "Hampus", item["id"], "no", None, NOW)

    assert different == (
        {"event": "answered", "id": item["id"], "answer": "different", "reason": "jargon", "at": NOW},
        {**source, "reasons": ["tone", "jargon"], "matched_by": "claude", "swipe": swipe_id(source), "match": item["id"], "counted": "confirmed", "at": NOW},
    )
    assert no == ({"event": "answered", "id": item["id"], "answer": "no", "at": NOW}, None)


@pytest.mark.parametrize("second", ["yes", "no", "different"])
def test_a_second_answer_writes_nothing(second: str) -> None:
    source = label()
    item = asked(source, ["generic"])
    first = {"event": "answered", "id": item["id"], "answer": "yes", "at": NOW}

    assert answer([source], [item, first], {"generic", "tone"}, "Hampus", item["id"], second, "tone" if second == "different" else None, NOW) is None


def test_answer_refuses_a_missing_or_stale_item_and_a_dead_reason() -> None:
    mine = label(card="d:c1")
    theirs = label(card="d:c1", grader="Levon")
    sure = label(card="d:c2")
    replaced = label(card="d:c3")
    labels = [mine, theirs, sure, replaced, label(card="d:c3", at=NOW, verdict="good", note="")]
    items = {"mine": asked(mine, ["generic"]), "theirs": asked(theirs, ["generic"]), "sure": asked(sure, ["generic"], kind="sure"), "replaced": asked(replaced, ["generic"])}
    events = list(items.values())

    def refusal(item: str, choice: str = "yes", reason: str | None = None, covered: frozenset[str] = frozenset({"generic"})) -> object:
        return answer(labels, events, set(covered), "Hampus", items[item]["id"] if item in items else item, choice, reason, NOW)

    assert refusal("m_nope") == Refusal("missing", "no match m_nope")
    assert refusal("theirs") == Refusal("missing", f"no match {items['theirs']['id']}")
    assert refusal("sure") == Refusal("missing", f"no match {items['sure']['id']}")
    assert refusal("replaced") == Refusal("stale", "out of date: the card was swiped again, or no check stands for its reasons")
    assert refusal("mine", covered=frozenset()) == Refusal("stale", "out of date: the card was swiped again, or no check stands for its reasons")
    assert refusal("mine", "different", "vague") == Refusal("invalid", 'no check stands for "vague"')


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        ([1], "body must be a JSON object"),
        ({"answer": "maybe"}, "answer must be yes, no, different, undo or redo"),
        ({"answer": "different"}, "a different chip needs the reason picked"),
        ({"answer": "different", "reason": 3}, "a different chip needs the reason picked"),
        ({"answer": "yes"}, None),
        ({"answer": "different", "reason": "generic"}, None),
    ],
)
def test_answer_problem(body: object, problem: str | None) -> None:
    assert answer_problem(body) == problem


LATER = "2026-11-21T11:00:00+00:00"


def sure_match(source: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Claude was sure the source's note means jargon: the labels with its matched line, and the events."""
    proposal = propose([source], [], {"jargon"}, swipe_id(source), ["jargon"], "Quotes HRV", NOW, "sure")
    assert not isinstance(proposal, Refusal)
    event, line = proposal
    assert line is not None
    return [source, line], [event]


def test_undo_writes_the_swipes_own_reasons_back() -> None:
    source = label(reasons=["generic"])
    labels, events = sure_match(source)
    match = events[0]["id"]

    writes = undo(labels, events, {"jargon"}, "Hampus", match, "undo", LATER)

    assert writes == (
        {"event": "undone", "id": match, "at": LATER},
        {**source, "reasons": ["generic"], "matched_by": "claude", "swipe": swipe_id(source), "match": match, "counted": "undone", "at": LATER},
    )
    assert writes is not None and not isinstance(writes, Refusal)
    assert current([*labels, writes[1]]) == [writes[1]]


def test_redo_writes_the_matched_reasons_again() -> None:
    source = label(reasons=["generic"])
    labels, events = sure_match(source)
    match = events[0]["id"]
    undone = undo(labels, events, {"jargon"}, "Hampus", match, "undo", LATER)
    assert undone is not None and not isinstance(undone, Refusal)

    writes = undo([*labels, undone[1]], [*events, undone[0]], {"jargon"}, "Hampus", match, "redo", "2026-11-21T12:00:00+00:00")

    assert writes == (
        {"event": "redone", "id": match, "at": "2026-11-21T12:00:00+00:00"},
        {**source, "reasons": ["generic", "jargon"], "matched_by": "claude", "swipe": swipe_id(source), "match": match, "counted": "sure", "at": "2026-11-21T12:00:00+00:00"},
    )


def test_a_repeat_undo_or_redo_writes_nothing() -> None:
    labels, events = sure_match(label())
    match = events[0]["id"]
    undone = undo(labels, events, {"jargon"}, "Hampus", match, "undo", LATER)
    assert undone is not None and not isinstance(undone, Refusal)

    assert undo(labels, events, {"jargon"}, "Hampus", match, "redo", LATER) is None
    assert undo([*labels, undone[1]], [*events, undone[0]], {"jargon"}, "Hampus", match, "undo", LATER) is None


def test_undo_refuses_another_graders_match_an_ask_and_a_stale_match() -> None:
    labels, events = sure_match(label())
    match = events[0]["id"]
    ask = label(card="d:c18")
    events = [*events, asked(ask, ["jargon"])]
    labels = [*labels, ask]
    reswiped = [*labels, label(at=LATER, verdict="good", note="")]

    assert undo(labels, events, {"jargon"}, "Levon", match, "undo", LATER) == Refusal("missing", f"no match {match}")
    assert undo(labels, events, {"jargon"}, "Hampus", events[1]["id"], "undo", LATER) == Refusal("missing", f"no match {events[1]['id']}")
    assert undo(labels, events, {"jargon"}, "Hampus", "m_000000000000", "undo", LATER) == Refusal("missing", "no match m_000000000000")
    assert undo(reswiped, events, {"jargon"}, "Hampus", match, "undo", LATER) == Refusal("stale", "out of date: the card was swiped again, or no check stands for its reasons")


def test_sure_items_list_the_graders_live_sure_matches_and_whether_undone() -> None:
    mine = label(card="d:c1", note="Says HRV")
    labels, events = sure_match(mine)
    replaced = label(card="d:c2")
    theirs = label(card="d:c3", grader="Levon")
    ask = label(card="d:c4")
    for other in (replaced, theirs):
        more_labels, more_events = sure_match(other)
        labels, events = [*labels, *more_labels], [*events, *more_events]
    labels = [*labels, ask, label(card="d:c2", at=LATER, verdict="good", note="")]
    events = [*events, asked(ask, ["jargon"])]
    listed = {"id": events[0]["id"], "card_id": "d:c1", "note": "Says HRV", "reasons": ["jargon"], "undone": False}

    assert sure_items(labels, events, {"jargon"}, "Hampus") == [listed]
    undone = [*events, {"event": "undone", "id": events[0]["id"], "at": LATER}]
    assert sure_items(labels, undone, {"jargon"}, "Hampus") == [{**listed, "undone": True}]
    redone = [*undone, {"event": "redone", "id": events[0]["id"], "at": LATER}]
    assert sure_items(labels, redone, {"jargon"}, "Hampus") == [listed]


def test_an_undone_note_is_an_idea_until_redone() -> None:
    source = label(reasons=["generic"], note="Says HRV")
    labels, events = sure_match(source)
    match = events[0]["id"]
    undone = [*events, {"event": "undone", "id": match, "at": LATER}]
    covered = {"jargon", "generic"}

    assert idea_lines(labels, events, covered) == [{**source, "note": ""}]
    assert idea_lines(labels, undone, covered) == [{**source, "reasons": []}]
    assert idea_lines(labels, [*undone, {"event": "redone", "id": match, "at": LATER}], covered) == [{**source, "note": ""}]


def test_undone_count_counts_the_rules_sure_matches_undone_now() -> None:
    labels, events = sure_match(label(card="d:c1"))
    for card in ("d:c2", "d:c3"):
        more_labels, more_events = sure_match(label(card=card))
        labels, events = [*labels, *more_labels], [*events, *more_events]
    undone = [{"event": "undone", "id": event["id"], "at": LATER} for event in events]
    redone = {"event": "redone", "id": events[2]["id"], "at": LATER}
    stale = label(card="d:c1", at=LATER, verdict="good", note="")

    assert undone_count(labels, events, {"jargon"}, {"jargon"}) == 0
    assert undone_count([*labels, stale], [*events, *undone, redone], {"jargon"}, {"jargon"}) == 1
    assert undone_count(labels, [*events, *undone], {"jargon"}, {"tone"}) == 0


def test_a_check_brought_back_does_not_revive_a_match_made_again_since() -> None:
    labels, events = sure_match(label())
    again = propose(labels, events, {"tone"}, swipe_id(label()), ["tone"], "Too formal", NOW, "ask")  # jargon's judge was deleted
    assert not isinstance(again, Refusal)
    events = [*events, again[0]]

    back = {"jargon", "tone"}  # and then restored

    assert sure_items(labels, events, back, "Hampus") == []
    assert [item["id"] for item in pending(labels, events, back, "Hampus")] == [again[0]["id"]]


def test_a_counting_line_left_by_a_crash_is_the_answer() -> None:
    source = label()
    item = asked(source, ["generic"])
    # The server wrote the Yes's line, then died before its `answered` event.
    leftover = {**source, "reasons": ["generic"], "matched_by": "claude", "swipe": swipe_id(source), "match": item["id"], "counted": "confirmed", "at": NOW}

    assert pending([source, leftover], [item], {"generic"}, "Hampus") == []
    assert answer([source, leftover], [item], {"generic"}, "Hampus", item["id"], "no", None, NOW) is None
    assert kept_and_waiting([source, leftover], [item], {"generic"}) == (0, {})


def test_an_undo_line_left_by_a_crash_is_the_undo() -> None:
    labels, events = sure_match(label())
    # The server wrote the undo's line, then died before its `undone` event.
    leftover = {**label(), "matched_by": "claude", "swipe": swipe_id(label()), "match": events[0]["id"], "counted": "undone", "at": "2026-11-21T11:00:00+00:00"}

    assert [item["undone"] for item in sure_items([*labels, leftover], events, {"jargon"}, "Hampus")] == [True]
    assert undo([*labels, leftover], events, {"jargon"}, "Hampus", events[0]["id"], "undo", NOW) is None
