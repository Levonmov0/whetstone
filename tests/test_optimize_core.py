import pytest

from whetstone.features.optimize.core import SplitError, split_cases


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
