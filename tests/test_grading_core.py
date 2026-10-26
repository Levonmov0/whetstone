from datetime import UTC, datetime, timedelta

import pytest

from whetstone.features.grading.core import disagreements, idle_expired


def swipe(grader: str, verdict: str, card: str = "X", settled: bool = False) -> dict[str, object]:
    label: dict[str, object] = {"card_id": card, "grader": grader, "verdict": verdict}
    return {**label, "settled": True} if settled else label


@pytest.mark.parametrize(
    ("labels", "queued"),
    [
        ([swipe("Levon", "good"), swipe("Hampus", "bad")], ["X"]),
        ([swipe("Levon", "good"), swipe("Hampus", "good")], []),
        ([swipe("Levon", "good"), swipe("Hampus", "skip")], []),
        ([swipe("Levon", "good"), swipe("Hampus", "bad"), swipe("Hampus", "good")], []),
        ([swipe("Levon", "good"), swipe("Hampus", "bad"), swipe("Levon", "bad", settled=True)], []),
        ([swipe("Levon", "good"), swipe("Hampus", "bad"), swipe("Levon", "bad", settled=True), swipe("Robin", "good")], []),
        ([swipe("Levon", "good", "Y"), swipe("Hampus", "bad", "Y"), swipe("Levon", "good", "X"), swipe("Hampus", "bad", "X")], ["Y", "X"]),
    ],
)
def test_disagreements(labels: list[dict[str, object]], queued: list[str]) -> None:
    assert disagreements(labels) == queued


@pytest.mark.parametrize(("idle_hours", "expired"), [(11.9, False), (12, True), (13, True)])
def test_idle_expired(idle_hours: float, expired: bool) -> None:
    last = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)
    assert idle_expired(last, last + timedelta(hours=idle_hours), timedelta(hours=12)) is expired
