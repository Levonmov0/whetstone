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
    raise NotImplementedError
