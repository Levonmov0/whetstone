import pytest

from whetstone.features.optimize.core import SplitError, length_factor, placeholder_problem, split_cases


def test_split_cases_is_40_25_35_disjoint_and_stable() -> None:
    ids = [f"case-{i}" for i in range(20)]

    train, select, held = split_cases(ids)

    assert (len(train), len(select), len(held)) == (8, 5, 7)
    assert sorted(train + select + held) == sorted(ids)
    assert split_cases(list(reversed(ids))) == (train, select, held)


def test_split_cases_gives_each_set_one_of_three() -> None:
    train, select, held = split_cases(["a", "b", "c"])

    assert (len(train), len(select), len(held)) == (1, 1, 1)


def test_split_cases_needs_three() -> None:
    with pytest.raises(SplitError, match="a run needs at least 3 cases; this prompt has 2"):
        split_cases(["a", "b"])


@pytest.mark.parametrize(("length", "factor"), [(100, 1.0), (150, 1.0), (225, 2 / 3), (300, 0.5)])
def test_length_factor_scores_down_versions_over_one_and_a_half_times_the_original(length: int, factor: float) -> None:
    assert length_factor(original=100, length=length) == pytest.approx(factor)


ORIGINAL = "Hi {{name}}, see you ${day}."


@pytest.mark.parametrize(
    ("original", "candidate", "problem"),
    [
        (ORIGINAL, "Hello {{name}}. Until ${day}.", None),
        (ORIGINAL, "Hello, see you ${day}.", "drops placeholder {{name}}"),
        (ORIGINAL, "Hi {{name}}, see you ${date}.", "drops placeholder ${day}; adds placeholder ${date}"),
        ('Return { "ask": null }.', 'Answer { "ask": null } only.', None),
        ("{{name}} and {{name}} again", "{{name}} once", "drops placeholder {{name}}"),
    ],
)
def test_placeholder_problem(original: str, candidate: str, problem: str | None) -> None:
    assert placeholder_problem(original, candidate) == problem
