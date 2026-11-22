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


def unmatched_notes(labels: list[dict[str, Any]], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The latest bad swipes that carry a note and have no proposal yet."""
    proposed = {event["swipe"] for event in events if event["event"] == "proposed"}
    return [label for label in latest_swipes(labels).values() if label["verdict"] == "bad" and label["note"] and swipe_id(label) not in proposed]


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


def propose(labels: list[dict[str, Any]], events: list[dict[str, Any]], covered: set[str], swipe: str, reasons: list[str], why: str, at: str) -> str | tuple[dict[str, Any], dict[str, Any]]:
    """Claude's match of one swipe's note to reasons: the refusal, or the `proposed` event and the matched label line
    to append. Only a grader's latest bad swipe can be matched, once, and only to reasons some check stands for."""
    source = next((label for label in labels if "matched_by" not in label and swipe_id(label) == swipe), None)
    if source is None:
        return f"no swipe {swipe}"
    if source["verdict"] != "bad":
        return "not a bad swipe"
    if latest_swipes(labels)[source["grader"], source["card_id"]] is not source:
        return f"{source['grader']} swiped {source['card_id']} again, matching the new note instead"
    if uncovered := [reason for reason in reasons if reason not in covered]:
        return f'no check stands for "{uncovered[0]}"'
    if any(event["event"] == "proposed" and event["swipe"] == swipe for event in events):
        return "already matched"
    raise NotImplementedError
