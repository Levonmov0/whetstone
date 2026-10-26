"""Pure rules for grading: no I/O, environment or SDKs."""

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
