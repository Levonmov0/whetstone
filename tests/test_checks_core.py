import pytest

from whetstone.features.checks.core import Agreement, Side, agreement, judge_gate, optimize_gate, uncovered_reasons


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


def rows_none() -> dict[str, Agreement]:
    return {}


def rows(good: tuple[int, int], bad: tuple[int, int], **others: tuple[tuple[int, int], tuple[int, int]]) -> dict[str, Agreement]:
    return {"Levon": Agreement(Side(*good), Side(*bad)), **{name: Agreement(Side(*g), Side(*b)) for name, (g, b) in others.items()}}


NO_ADVICE: list[str] = []


@pytest.mark.parametrize(
    ("agreements", "gate"),
    [
        (rows((9, 10), (5, 5)), ("trusted", NO_ADVICE)),
        (rows((17, 20), (5, 5)), ("warn", ["agrees with Levon on 85% of good cards; below 90% is a warning"])),
        (rows((8, 10), (5, 5)), ("warn", ["agrees with Levon on 80% of good cards; below 90% is a warning"])),
        (rows((10, 10), (17, 20)), ("warn", ["agrees with Levon on 85% of bad cards for this rule; below 90% is a warning"])),
        (rows((7, 10), (5, 5)), ("untrusted", ["fails outputs Levon called good (70%); sharpen the rubric"])),
        (rows((10, 10), (3, 5)), ("untrusted", ["misses problems Levon flagged (60%); sharpen the rubric or swipe more examples"])),
        (rows((10, 10), (3, 3)), ("untrusted", ["only 3 bad swipes for this rule; swipe at least 2 more"])),
        (rows((3, 3), (5, 5)), ("untrusted", ["only 3 good swipes; swipe at least 2 more"])),
        (rows((10, 10), (5, 5), Hampus=((0, 2), (0, 0))), ("trusted", NO_ADVICE)),
        (rows((10, 10), (5, 5), Hampus=((6, 10), (5, 5))), ("untrusted", ["fails outputs Hampus called good (60%); sharpen the rubric"])),
        (rows_none(), ("untrusted", ["only 0 good swipes; swipe at least 5 more", "only 0 bad swipes for this rule; swipe at least 5 more"])),
    ],
)
def test_judge_gate(agreements: dict[str, Agreement], gate: tuple[str, list[str]]) -> None:
    assert judge_gate(agreements) == gate


def no_gates() -> dict[str, tuple[str, list[str]]]:
    return {}


@pytest.mark.parametrize(
    ("gates", "decision"),
    [
        (no_gates(), (True, NO_ADVICE)),
        ({"assumes": ("trusted", NO_ADVICE)}, (True, NO_ADVICE)),
        ({"assumes": ("trusted", NO_ADVICE), "voice": ("warn", ["agrees with Levon on 85% of good cards; below 90% is a warning"])},
         (True, ["voice: agrees with Levon on 85% of good cards; below 90% is a warning"])),
        ({"assumes": ("untrusted", ["fails outputs Levon called good (70%); sharpen the rubric"]), "voice": ("warn", ["w"])},
         (False, ["assumes: fails outputs Levon called good (70%); sharpen the rubric"])),
    ],
)
def test_optimize_gate(gates: dict[str, tuple[str, list[str]]], decision: tuple[bool, list[str]]) -> None:
    assert optimize_gate(gates) == decision
