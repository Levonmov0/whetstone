import pytest

from whetstone.features.grading.core import disagreements


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
