"""Pure rules for matching graders' notes to the reasons checks stand for: no I/O, environment or SDKs."""

import hashlib
import json
from typing import Any


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
    for event in events:
        if event["event"] == "answered":
            answers.setdefault(event["id"], event)  # the first answer wins
    items: list[dict[str, Any]] = []
    for event in events:
        if event["event"] != "proposed":
            continue
        source = swipes[event["swipe"]]
        answer = answers.get(event["id"])
        replaced = latest[source["grader"], source["card_id"]] is not source
        dead = not (answer and answer["answer"] == "no") and not covered & set(event["reasons"])
        items.append({**event, "source": source, "answer": answer, "stale": replaced or dead})
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


def evidence(labels: list[dict[str, Any]], rule: set[str]) -> tuple[int, int]:
    """Of the bad swipes that count for a rule, how many the grader tapped it on, and how many count only because
    Claude was sure of their note."""
    swipes = {swipe_id(label): label for label in labels if "matched_by" not in label}
    tapped = sure = 0
    for line in current(labels):
        if line["verdict"] != "bad" or not rule & set(line["reasons"]):
            continue
        if "matched_by" in line and not rule & set(swipes[line["swipe"]]["reasons"]):
            sure += 1
        else:
            tapped += 1
    return tapped, sure


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


def answer(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str], grader: str, match: str, choice: str, reason: str | None, at: str) -> Any:
    raise NotImplementedError
