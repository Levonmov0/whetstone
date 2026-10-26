"""Pure rules for grading: no I/O, environment or SDKs."""


def swipe_reasons(verdict: str, reasons: list[str], caught_by: list[str]) -> list[str]:
    """A bad swipe with no reasons on a card a check already catches is about what that check caught."""
    if verdict == "bad" and not reasons:
        return caught_by
    return reasons
