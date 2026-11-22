"""Pure rules for matching graders' notes to the reasons checks stand for: no I/O, environment or SDKs."""

import hashlib
import json
from typing import Any, NamedTuple, cast


class Refusal(NamedTuple):
    kind: str  # missing, stale or invalid
    message: str


def swipe_id(label: dict[str, Any]) -> str:
    """A swipe's id, derived from the label line itself so existing lines need no migration."""
    digest = hashlib.sha256(json.dumps([label["grader"], label["card_id"], label["at"]]).encode()).hexdigest()
    return f"s_{digest[:12]}"


def latest_swipes(labels: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Each grader's newest swipe on each card. A matched line is Claude's, never a swipe."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    # Labels come from several files; their time (ISO, UTC) puts them back in the order they were written.
    for label in sorted(labels, key=lambda label: str(label.get("at", ""))):
        if "matched_by" not in label:
            latest[label["grader"], label["card_id"]] = label
    return latest


def unmatched_notes(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str]) -> list[dict[str, Any]]:
    """The latest bad swipes that carry a note and have no live proposal: none yet, or only stale ones."""
    proposed = {item["swipe"] for item in _items(labels, events, covered) if not item["stale"]}
    return [label for label in latest_swipes(labels).values() if label["verdict"] == "bad" and label["note"] and swipe_id(label) not in proposed]


def _items(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str]) -> list[dict[str, Any]]:
    """Each proposal, folded with its first answer and its source swipe. It is stale once the grader swiped the card
    again, or once no check stands for any of its reasons, unless the grader said No: their note is an idea either way."""
    swipes = {swipe_id(label): label for label in labels if "matched_by" not in label}
    latest = latest_swipes(labels)
    answers: dict[str, dict[str, Any]] = {}
    undone: dict[str, bool] = {}
    for event in events:
        if event["event"] == "answered":
            answers.setdefault(event["id"], event)  # the first answer wins
        elif event["event"] in ("undone", "redone"):
            undone[event["id"]] = event["event"] == "undone"  # the latest undo or redo wins
    items: list[dict[str, Any]] = []
    for event in events:
        if event["event"] != "proposed":
            continue
        source = swipes[event["swipe"]]
        answer = answers.get(event["id"])
        replaced = latest[source["grader"], source["card_id"]] is not source
        dead = not (answer and answer["answer"] == "no") and not covered & set(event["reasons"])
        items.append({**event, "source": source, "answer": answer, "undone": undone.get(event["id"], False), "stale": replaced or dead})
    return items


def current(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One line per grader and card: their latest swipe, or the newest matched line made from it. A matched line made
    from a swipe since replaced never counts, whichever order the two were written in."""
    latest = latest_swipes(labels)
    lines = dict(latest)
    for label in sorted(labels, key=lambda label: str(label.get("at", ""))):
        key = label["grader"], label["card_id"]
        if "matched_by" in label and label["swipe"] == swipe_id(latest[key]):
            lines[key] = label
    return list(lines.values())


def propose(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str], swipe: str, reasons: list[str], why: str, at: str, kind: str = "sure") -> str | tuple[dict[str, Any], dict[str, Any] | None]:
    """Claude's match of one swipe's note to reasons: the refusal, or the `proposed` event and, for a sure match, the
    matched label line to append; an ask match waits for the grader. Only a grader's latest bad swipe can be matched, once, and only to reasons some check stands for."""
    source = next((label for label in labels if "matched_by" not in label and swipe_id(label) == swipe), None)
    if source is None:
        return f"no swipe {swipe}"
    if source["verdict"] != "bad":
        return "not a bad swipe"
    if latest_swipes(labels)[source["grader"], source["card_id"]] is not source:
        return f"{source['grader']} swiped {source['card_id']} again, matching the new note instead"
    if uncovered := [reason for reason in reasons if reason not in covered]:
        return f'no check stands for "{uncovered[0]}"'
    earlier = [item for item in _items(labels, events, covered) if item["swipe"] == swipe]
    if any(not item["stale"] for item in earlier):
        return "already matched"
    # A swipe has one live proposal at a time; one made after its earlier ones went stale gets its own id.
    match = "m_" + swipe.removeprefix("s_") + (f"_{len(earlier) + 1}" if earlier else "")
    event = {"event": "proposed", "id": match, "swipe": swipe, "grader": source["grader"], "card_id": source["card_id"], "kind": kind, "reasons": reasons, "why": why, "at": at}
    if kind == "ask":
        return event, None
    line = {**source, "reasons": list(dict.fromkeys(source["reasons"] + reasons)), "matched_by": "claude", "swipe": swipe, "match": match, "counted": "sure", "at": at}
    return event, line


def idea_lines(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str]) -> list[dict[str, Any]]:
    """The swipes new-check ideas come from. A note a match counts, or one waiting on its grader, is no idea; a note
    answered No stands on its own, whatever chips were tapped. Matched lines are Claude's, never a swipe."""
    items = {item["swipe"]: item for item in _items(labels, events, covered) if not item["stale"]}
    lines: list[dict[str, Any]] = []
    for line in labels:
        if "matched_by" in line:
            continue
        item = items.get(swipe_id(line))
        if item and (item["undone"] or item["answer"] and item["answer"]["answer"] == "no"):  # an undo says Claude was wrong, as a No does
            line = {**line, "reasons": [reason for reason in line["reasons"] if reason not in covered]}
        elif item:
            line = {**line, "note": ""}
        lines.append(line)
    return lines


def kept_and_waiting(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str]) -> tuple[int, dict[str, int]]:
    """How many notes graders answered No to, kept as ideas for a new check, and how many asks wait on each grader."""
    items = [item for item in _items(labels, events, covered) if not item["stale"]]
    kept = sum(1 for item in items if item["answer"] and item["answer"]["answer"] == "no")
    waiting: dict[str, int] = {}
    for item in items:
        if item["kind"] == "ask" and not item["answer"]:
            waiting[item["grader"]] = waiting.get(item["grader"], 0) + 1
    return kept, waiting


def evidence(labels: list[dict[str, Any]], rule: set[str]) -> tuple[int, int, int]:
    """Of the bad swipes that count for a rule, how many the grader tapped it on, how many count only because Claude
    was sure of their note, and how many because the grader said yes to Claude's match."""
    swipes = {swipe_id(label): label for label in labels if "matched_by" not in label}
    tapped = sure = confirmed = 0
    for line in current(labels):
        if line["verdict"] != "bad" or not rule & set(line["reasons"]):
            continue
        if "matched_by" not in line or rule & set(swipes[line["swipe"]]["reasons"]):
            tapped += 1
        elif line["counted"] == "confirmed":
            confirmed += 1
        else:
            sure += 1
    return tapped, sure, confirmed


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


def answer(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str], grader: str, match: str, choice: str, reason: str | None, at: str) -> Refusal | tuple[dict[str, Any], dict[str, Any] | None] | None:
    """The grader's answer to their own ask match: the refusal, nothing to write when it was already answered (the first answer wins, so a
    double tap or a second phone counts once), else the `answered` event and the matched label line that makes the swipe count,
    confirmed by the grader. Yes counts the suggested reasons some check still stands for, a different chip only the
    one picked; No leaves the swipe as it was."""
    item = next((item for item in _items(labels, events, covered) if item["id"] == match and item["kind"] == "ask" and item["grader"] == grader), None)
    if item is None:
        return Refusal("missing", f"no match {match}")  # another grader's match looks the same as no match at all
    if item["stale"]:
        return STALE
    if item["answer"]:
        return None
    if reason is not None and reason not in covered:
        return Refusal("invalid", f'no check stands for "{reason}"')
    event = {"event": "answered", "id": match, "answer": choice, **({"reason": reason} if choice == "different" else {}), "at": at}
    if choice == "no":
        return event, None
    source = item["source"]
    counted = [reason] if reason is not None else [r for r in item["reasons"] if r in covered]
    line = {**source, "reasons": list(dict.fromkeys(source["reasons"] + counted)), "matched_by": "claude", "swipe": item["swipe"], "match": match, "counted": "confirmed", "at": at}
    return event, line


def answer_problem(body: object) -> str | None:
    """Why an answer from the app can't be stored, or None when it can. The match itself is looked up by the caller."""
    if not isinstance(body, dict):
        return "body must be a JSON object"
    sent = cast(dict[str, Any], body)
    if sent.get("answer") not in ("yes", "no", "different"):
        return "answer must be yes, no or different"
    if sent["answer"] == "different" and not isinstance(sent.get("reason"), str):
        return "a different chip needs the reason picked"
    return None


def undo(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str], grader: str, match: str, choice: str, at: str) -> Refusal | tuple[dict[str, Any], dict[str, Any]] | None:
    """The grader's undo or redo of Claude's sure match of their note. Undo makes the swipe count as it did before the
    match, redo as matched again."""
    item = next((item for item in _items(labels, events, covered) if item["id"] == match and item["kind"] == "sure" and item["grader"] == grader), None)
    if item is None:
        return Refusal("missing", f"no match {match}")  # another grader's, or an ask: only one's own sure matches undo
    if item["stale"]:
        return STALE
    if item["undone"] == (choice == "undo"):
        return None  # already so: a double tap or a second phone writes once
    source = item["source"]
    if choice == "redo":
        reasons, counted, event = list(dict.fromkeys(source["reasons"] + item["reasons"])), "sure", "redone"
    else:
        reasons, counted, event = source["reasons"], "undone", "undone"
    line = {**source, "reasons": reasons, "matched_by": "claude", "swipe": item["swipe"], "match": match, "counted": counted, "at": at}
    return {"event": event, "id": match, "at": at}, line


def sure_items(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str], grader: str) -> list[dict[str, Any]]:
    """The grader's sure matches that still stand, as the app lists them with Undo or Redo."""
    return [
        {"id": item["id"], "card_id": item["card_id"], "note": item["source"]["note"], "reasons": [r for r in item["reasons"] if r in covered], "undone": item["undone"]}
        for item in _items(labels, events, covered)
        if item["kind"] == "sure" and item["grader"] == grader and not item["stale"]
    ]
