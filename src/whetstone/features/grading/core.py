"""Pure rules for grading: no I/O, environment or SDKs."""

from datetime import datetime, timedelta
from typing import Any, cast


def swipe_reasons(verdict: str, reasons: list[str], caught_by: list[str]) -> list[str]:
    """A bad swipe with no reasons on a card a check already catches is about what that check caught."""
    if verdict == "bad" and not reasons:
        return caught_by
    return reasons


MAX_NOTE = 10_000


def swipe_problem(body: object) -> str | None:
    """Why a swipe from the app can't be stored, or None when it can. The card itself is looked up by the caller."""
    if not isinstance(body, dict):
        return "body must be a JSON object"
    swipe = cast(dict[str, Any], body)
    if swipe.get("verdict") not in ("good", "bad", "skip"):
        return "verdict must be good, bad or skip"
    grader = swipe.get("grader")
    if not isinstance(grader, str) or not grader.strip():
        return "grader is required"
    reasons = swipe.get("reasons")
    if not isinstance(reasons, list) or not all(isinstance(r, str) for r in cast(list[Any], reasons)):
        return "reasons must be a list of text"
    note = swipe.get("note")
    if not isinstance(note, str):
        return "note must be text"
    if len(note) > MAX_NOTE:
        return f"note is over {MAX_NOTE} characters"
    return None


def disagreements(labels: list[dict[str, Any]]) -> list[str]:
    """Cards where one grader's latest swipe is good and another's is bad, unless settled; in first-swiped order."""
    latest: dict[str, dict[str, str]] = {}
    settled: set[str] = set()
    for label in labels:
        if label.get("settled"):
            settled.add(label["card_id"])
        latest.setdefault(label["card_id"], {})[label["grader"]] = label["verdict"]
    return [card for card, verdicts in latest.items() if card not in settled and {"good", "bad"} <= set(verdicts.values())]


def idle_expired(last_activity: datetime, now: datetime, limit: timedelta) -> bool:
    raise NotImplementedError
