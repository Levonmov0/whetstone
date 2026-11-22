"""Pure rules for matching graders' notes to the reasons checks stand for: no I/O, environment or SDKs."""

import hashlib
import itertools
import json
from typing import Any, NamedTuple, cast


class Refusal(NamedTuple):
    kind: str  # missing, stale or invalid
    message: str


def swipe_id(label: dict[str, Any]) -> str:
    """A swipe's id, derived from the label line itself so existing lines need no migration."""
    digest = hashlib.sha256(json.dumps([label["grader"], label["card_id"], label["at"]]).encode()).hexdigest()
    return f"s_{digest[:12]}"


def _by_time(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Labels come from several files; their time (ISO, UTC) puts them back in the order they were written.
    return sorted(labels, key=lambda label: str(label.get("at", "")))


def _swipes(labels: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Every swipe by its id. A matched line is Claude's, never a swipe."""
    return {swipe_id(label): label for label in labels if "matched_by" not in label}


def _matched_line(source: dict[str, Any], match: str, reasons: list[str], counted: str, at: str) -> dict[str, Any]:
    """The label line that makes a swipe count with `reasons`: the swipe as it was, its verdict untouched, marked Claude's."""
    return {**source, "reasons": reasons, "matched_by": "claude", "swipe": swipe_id(source), "match": match, "counted": counted, "at": at}


def latest_swipes(labels: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Each grader's newest swipe on each card. A matched line is Claude's, never a swipe."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for label in _by_time(labels):
        if "matched_by" not in label:
            latest[label["grader"], label["card_id"]] = label
    return latest


def unmatched_notes(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str]) -> list[dict[str, Any]]:
    """The latest bad swipes that carry a note and have no live proposal: none yet, or only stale ones."""
    proposed = {item["swipe"] for item in _items(labels, events, covered) if not item["stale"]}
    return [label for label in latest_swipes(labels).values() if label["verdict"] == "bad" and label["note"] and swipe_id(label) not in proposed]


# The lines each kind of match writes: a sure match counts or is undone, an ask counts once its grader confirms it.
WRITES = {"sure": ("sure", "undone"), "ask": ("confirmed",)}


def _items(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str]) -> list[dict[str, Any]]:
    """Each proposal, folded with its first answer and its source swipe. It is stale once the grader swiped the card
    again, or once no check stands for any of its reasons, unless the grader said No: their note is an idea either way."""
    swipes = _swipes(labels)
    latest = latest_swipes(labels)
    # A No is an event; a Yes or a different chip is the confirmed line that makes the swipe count, and says which.
    noes = [event for event in events if event["event"] == "answered"]
    confirmed = [line for line in labels if line.get("counted") == "confirmed"]
    answers: dict[str, dict[str, Any]] = {}
    for said in sorted(noes + confirmed, key=lambda each: str(each["at"])):  # the first answer wins
        answers.setdefault(said.get("match") or said["id"], {key: said[key] for key in ("answer", "reason") if key in said})
    # A sure match's newest line says whether the grader undid it.
    undone = {line["match"]: line["counted"] == "undone" for line in _by_time(labels) if line.get("counted") in WRITES["sure"]}
    proposals = [event for event in events if event["event"] == "proposed"]
    items: list[dict[str, Any]] = []
    for n, event in enumerate(proposals):
        source = swipes[event["swipe"]]
        answer = answers.get(event["id"])
        said_no = bool(answer and answer["answer"] == "no")
        replaced = latest[source["grader"], source["card_id"]] is not source
        dead = not said_no and not covered & set(event["reasons"])
        # Matched again since: one live proposal per swipe, even once a deleted check comes back.
        superseded = not said_no and any(later["swipe"] == event["swipe"] for later in proposals[n + 1:])
        items.append({**event, "source": source, "answer": answer, "said_no": said_no, "undone": undone.get(event["id"], False), "stale": replaced or dead or superseded})
    return items


def current(labels: list[dict[str, Any]], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One line per grader and card: their latest swipe, or the newest matched line made from it. A matched line made
    from a swipe since replaced never counts, whichever order the two were written in, and nor does one no proposal
    of its kind owns (a crash's leftover, or a line written after the events were read), nor one of a match its swipe
    was matched again since."""
    latest = latest_swipes(labels)
    proposals = [event for event in events if event["event"] == "proposed"]
    kinds = {event["id"]: event["kind"] for event in proposals}
    newest = {event["swipe"]: event["id"] for event in proposals}  # one live proposal per swipe: its newest
    lines = dict(latest)
    for label in _by_time(labels):
        key = label["grader"], label["card_id"]
        live = label.get("match") is not None and newest.get(label["swipe"]) == label["match"]
        owned = live and label.get("counted") in WRITES.get(kinds[label["match"]], ())
        if "matched_by" in label and owned and key in latest and label["swipe"] == swipe_id(latest[key]):
            lines[key] = label
    return list(lines.values())


def propose(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str], swipe: str, reasons: list[str], why: str, at: str, kind: str) -> Refusal | tuple[dict[str, Any], dict[str, Any] | None]:
    """Claude's match of one swipe's note to reasons: the refusal, or the `proposed` event and, for a sure match, the
    matched label line to append; an ask match waits for the grader. Only a grader's latest bad swipe can be matched, once, and only to reasons some check stands for."""
    source = _swipes(labels).get(swipe)
    if source is None:
        return Refusal("missing", f"no swipe {swipe}")
    if source["verdict"] != "bad":
        return Refusal("invalid", "not a bad swipe")
    if latest_swipes(labels)[source["grader"], source["card_id"]] is not source:
        return Refusal("stale", f"{source['grader']} swiped {source['card_id']} again, matching the new note instead")
    if uncovered := [reason for reason in reasons if reason not in covered]:
        return Refusal("invalid", f'no check stands for "{uncovered[0]}"')
    earlier = [item for item in _items(labels, events, covered) if item["swipe"] == swipe]
    # A note the grader answered No to is an idea, so a judge written from it may match it again, on other reasons.
    said_no = [item for item in earlier if not item["stale"] and item["said_no"]]
    if any(not item["stale"] and item not in said_no for item in earlier):
        return Refusal("invalid", "already matched")
    if rejected := [reason for reason in reasons if any(reason in item["reasons"] for item in said_no)]:
        return Refusal("invalid", f'{source["grader"]} answered No to "{rejected[0]}"')
    # A swipe has one live proposal at a time; one made after its earlier ones went stale gets its own id, and so does
    # one made after a crash left a line with no proposal, so that line never becomes this match's.
    used = {event["id"] for event in events if event["event"] == "proposed"} | {line["match"] for line in labels if "match" in line}
    base = "m_" + swipe.removeprefix("s_")
    match = next(m for m in itertools.chain([base], (f"{base}_{n}" for n in itertools.count(2))) if m not in used)
    event = {"event": "proposed", "id": match, "swipe": swipe, "grader": source["grader"], "card_id": source["card_id"], "kind": kind, "reasons": reasons, "why": why, "at": at}
    if kind == "ask":
        return event, None
    return event, _matched_line(source, match, list(dict.fromkeys(source["reasons"] + reasons)), "sure", at)


def idea_lines(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str]) -> list[dict[str, Any]]:
    """The swipes new-check ideas come from. A note a match counts, or one waiting on its grader, is no idea; a note
    answered No stands on its own, whatever chips were tapped. Matched lines are Claude's, never a swipe."""
    items = {item["swipe"]: item for item in _items(labels, events, covered) if not item["stale"]}
    lines: list[dict[str, Any]] = []
    for line in labels:
        if "matched_by" in line:
            continue
        item = items.get(swipe_id(line))
        if item and (item["undone"] or item["said_no"]):  # an undo says Claude was wrong, as a No does
            # A No'd note is named by its swipe, so a judge written from it can match it again; an undone one can't be yet.
            named = {} if item["undone"] else {"idea_of": swipe_id(line)}
            line = {**line, "reasons": [reason for reason in line["reasons"] if reason not in covered], **named}
        elif item:
            line = {**line, "note": ""}
        lines.append(line)
    return lines


def kept_and_waiting(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str]) -> tuple[int, dict[str, int]]:
    """How many notes graders answered No to, kept as ideas for a new check, and how many asks wait on each grader."""
    items = [item for item in _items(labels, events, covered) if not item["stale"]]
    latest = {item["swipe"]: item for item in items}.values()  # a note matched again after a No is no longer kept
    kept = sum(1 for item in latest if item["said_no"])
    waiting: dict[str, int] = {}
    for item in items:
        if item["kind"] == "ask" and not item["answer"]:
            waiting[item["grader"]] = waiting.get(item["grader"], 0) + 1
    return kept, waiting


def evidence(labels: list[dict[str, Any]], events: list[dict[str, Any]], rule: set[str]) -> tuple[int, int, int]:
    """Of the bad swipes that count for a rule, how many the grader tapped it on, how many count only because Claude
    was sure of their note, and how many because the grader said yes to Claude's match."""
    swipes = _swipes(labels)
    tapped = sure = confirmed = 0
    for line in current(labels, events):
        if line["verdict"] != "bad" or not rule & set(line["reasons"]):
            continue
        if "matched_by" not in line or rule & set(swipes[line["swipe"]]["reasons"]):
            tapped += 1
        elif line["counted"] == "confirmed":
            confirmed += 1
        else:
            sure += 1
    return tapped, sure, confirmed


def case_of(labels: list[dict[str, Any]], events: list[dict[str, Any]], event: dict[str, Any]) -> str:
    """The case an event is about: a real-data case's events go in its source folder. A No names only its match,
    so its card comes from the proposal."""
    card = event.get("card_id") or next(e["card_id"] for e in events if e["event"] == "proposed" and e["id"] == event["id"])
    return next(label["case_id"] for label in labels if label["card_id"] == card)


EXCERPT = 160


def excerpt(output: Any) -> str:
    """The start of an output, as text, for reading a note beside what it was about."""
    text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
    return text if len(text) <= EXCERPT else text[:EXCERPT] + "…"


def pending(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str], grader: str) -> list[dict[str, Any]]:
    """The grader's ask matches still waiting for an answer, as the app shows them: only the suggested reasons some
    check still stands for."""
    return [
        {"id": item["id"], "card_id": item["card_id"], "note": item["source"]["note"], "excerpt": excerpt(item["source"]["output"]), "reasons": [r for r in item["reasons"] if r in covered], "why": item["why"]}
        for item in _items(labels, events, covered)
        if item["kind"] == "ask" and item["grader"] == grader and not item["answer"] and not item["stale"]
    ]


STALE = Refusal("stale", "out of date: the card was swiped again, or no check stands for its reasons")


def _own_item(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str], grader: str, match: str, kind: str) -> Refusal | dict[str, Any]:
    """The grader's own live match of this kind, or why not: another grader's, or an ask for an undo, looks the same as no match at all."""
    item = next((item for item in _items(labels, events, covered) if item["id"] == match and item["kind"] == kind and item["grader"] == grader), None)
    if item is None:
        return Refusal("missing", f"no match {match}")
    return STALE if item["stale"] else item


def answer(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str], grader: str, match: str, choice: str, reason: str | None, at: str) -> Refusal | tuple[dict[str, Any] | None, dict[str, Any] | None] | None:
    """The grader's answer to their own ask match: the refusal, nothing to write when it was already answered (the first
    answer wins, so a double tap or a second phone counts once), else the one record to write: for No its `answered`
    event, for Yes or a different chip the matched label line that makes the swipe count, confirmed by the grader and
    carrying the answer. Yes counts the suggested reasons some check still stands for, a different chip only the
    one picked; No leaves the swipe as it was."""
    item = _own_item(labels, events, covered, grader, match, "ask")
    if isinstance(item, Refusal):
        return item
    if item["answer"]:
        return None
    if reason is not None and reason not in covered:
        return Refusal("invalid", f'no check stands for "{reason}"')
    if choice == "no":
        return {"event": "answered", "id": match, "answer": "no", "at": at}, None
    source = item["source"]
    counted = [reason] if reason is not None else [r for r in item["reasons"] if r in covered]
    line = _matched_line(source, match, list(dict.fromkeys(source["reasons"] + counted)), "confirmed", at)
    return None, {**line, "answer": choice, **({"reason": reason} if reason is not None else {})}


def said(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str], match: str) -> dict[str, str]:
    """The answer stored for a match, as the app shows it: what counts is the first answer, from whichever phone."""
    return next(item["answer"] for item in _items(labels, events, covered) if item["id"] == match)


def answer_problem(body: object) -> str | None:
    """Why an answer from the app can't be stored, or None when it can. The match itself is looked up by the caller."""
    if not isinstance(body, dict):
        return "body must be a JSON object"
    sent = cast(dict[str, Any], body)
    if sent.get("answer") not in ("yes", "no", "different", "undo", "redo"):
        return "answer must be yes, no, different, undo or redo"
    if sent["answer"] == "different" and not isinstance(sent.get("reason"), str):
        return "a different chip needs the reason picked"
    if sent["answer"] != "different" and "reason" in sent:
        return "only a different chip takes a reason"
    return None


def undo(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str], grader: str, match: str, choice: str, at: str) -> Refusal | dict[str, Any] | None:
    """The grader's undo or redo of Claude's sure match of their note: the matched line to write. Undo makes the swipe
    count as it did before the match, redo as matched again."""
    item = _own_item(labels, events, covered, grader, match, "sure")
    if isinstance(item, Refusal):
        return item
    if item["undone"] == (choice == "undo"):
        return None  # already so: a double tap or a second phone writes once
    source = item["source"]
    if choice == "redo":
        return _matched_line(source, match, list(dict.fromkeys(source["reasons"] + item["reasons"])), "sure", at)
    return _matched_line(source, match, source["reasons"], "undone", at)


def sure_items(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str], grader: str) -> list[dict[str, Any]]:
    """The grader's sure matches that still stand, as the app lists them with Undo or Redo."""
    return [
        {"id": item["id"], "card_id": item["card_id"], "note": item["source"]["note"], "reasons": [r for r in item["reasons"] if r in covered], "undone": item["undone"]}
        for item in _items(labels, events, covered)
        if item["kind"] == "sure" and item["grader"] == grader and not item["stale"]
    ]


def undone_count(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str], rule: set[str]) -> int:
    """How many of Claude's sure matches to a rule graders have undone, as things stand: a redo takes one back off."""
    return sum(1 for item in _items(labels, events, covered) if item["kind"] == "sure" and item["undone"] and not item["stale"] and rule & set(item["reasons"]))
