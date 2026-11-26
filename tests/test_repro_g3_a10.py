from whetstone.features.checks.core import uncovered_reasons


def test_uncovered_reasons_come_most_frequent_first() -> None:
    labels = [{"card_id": c, "grader": "Levon", "verdict": "bad", "reasons": [r], "note": ""}
              for c, r in [("1", "wrong voice"), ("2", "assumes the outcome"), ("3", "assumes the outcome"), ("4", "too long")]]

    assert uncovered_reasons(labels, covered=set()) == [("assumes the outcome", 2), ("wrong voice", 1), ("too long", 1)]
