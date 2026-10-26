import pytest

from whetstone.features.checks.core import Agreement, Side, agreement, uncovered_reasons


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


def label(card: str, verdict: str, reasons: list[str] | None = None, grader: str = "Levon", at: str = "1", settled: bool = False) -> dict[str, object]:
    swiped: dict[str, object] = {"card_id": card, "grader": grader, "verdict": verdict, "reasons": reasons or [], "note": "", "at": at}
    return {**swiped, "settled": True} if settled else swiped


RULE = {"assumes", "assumes the outcome"}
GOOD_TEN = [label(f"g{i}", "good") for i in range(10)]
BAD_FIVE = [label(f"b{i}", "bad", ["assumes the outcome"]) for i in range(5)]
JUDGE = {**{f"g{i}": i != 0 for i in range(10)}, **{f"b{i}": False for i in range(5)}}  # True: the judge passed it


@pytest.mark.parametrize(
    ("labels", "verdicts", "rows"),
    [
        (GOOD_TEN + BAD_FIVE, JUDGE, {"Levon": Agreement(Side(9, 10), Side(5, 5))}),
        ([label("x", "bad", ["too long"]), label("y", "skip")], {"x": False, "y": True}, {"Levon": Agreement(Side(0, 0), Side(0, 0))}),
        ([label("x", "bad", ["assumes"], at="1"), label("x", "good", at="2")], {"x": True}, {"Levon": Agreement(Side(1, 1), Side(0, 0))}),
        ([label("x", "good", at="1"), label("x", "bad", ["assumes the outcome"], at="2", settled=True)], {"x": True}, {"Levon": Agreement(Side(0, 0), Side(0, 1))}),
        (
            [label("x", "good"), label("x", "bad", ["assumes the outcome"], grader="Hampus")],
            {"x": True},
            {"Levon": Agreement(Side(1, 1), Side(0, 0)), "Hampus": Agreement(Side(0, 0), Side(0, 1))},
        ),
    ],
)
def test_agreement(labels: list[dict[str, object]], verdicts: dict[str, bool], rows: dict[str, Agreement]) -> None:
    assert agreement(labels, verdicts, RULE) == rows
