import pytest

from whetstone.features.checks.core import uncovered_reasons


def swipe(verdict: str, reasons: list[str], note: str = "", card: str = "X") -> dict[str, object]:
    return {"card_id": card, "grader": "Levon", "verdict": verdict, "reasons": reasons, "note": note}


@pytest.mark.parametrize(
    ("labels", "uncovered"),
    [
        (
            [swipe("bad", ["too long"]), swipe("bad", ["assumes the outcome"]), swipe("bad", [], "weird question")],
            [("assumes the outcome", 1), ('note: "weird question"', 1)],
        ),
        ([swipe("good", ["assumes the outcome"]), swipe("skip", [], "weird question")], []),
        ([swipe("bad", ["assumes the outcome"], card="X"), swipe("bad", ["assumes the outcome"], card="Y")], [("assumes the outcome", 2)]),
    ],
)
def test_uncovered_reasons(labels: list[dict[str, object]], uncovered: list[tuple[str, int]]) -> None:
    assert uncovered_reasons(labels, covered={"too long"}) == uncovered
