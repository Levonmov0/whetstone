import pytest

from whetstone.features.optimize.core import EstimateError, RoleCost, SplitError, case_score, estimate, progress_line, stop_for_cap, stuck_reasons, length_factor, placeholder_problem, split_cases


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


def test_case_score_is_the_share_of_checks_passed_times_the_length_factor() -> None:
    failures = {"length": ["Over 76 characters."], "no_number": [], "assumes (judge)": []}

    assert case_score(failures, factor=1.0) == (pytest.approx(2 / 3), "Broke these rules:\n- length: Over 76 characters.")
    assert case_score({"length": [], "no_number": []}, factor=0.5) == (0.5, "All checks passed.")


CHEAP_RUN = {
    "generation": RoleCost(calls=100, input_tokens=100_000, output_tokens=10_000, dollars=0.15),
    "judge": RoleCost(calls=100, input_tokens=50_000, output_tokens=1_000, dollars=0.20),
    "rewrite": RoleCost(calls=10, input_tokens=40_000, output_tokens=8_000, dollars=0.50),
}


def test_estimate_scales_the_cheap_run_to_the_production_price() -> None:
    assert estimate(CHEAP_RUN, price=(3, 15), planned_generations=150) == pytest.approx(1.725)


def test_estimate_needs_the_cheap_runs_dollars() -> None:
    unknown = {**CHEAP_RUN, "judge": RoleCost(calls=100, input_tokens=50_000, output_tokens=1_000, dollars=None)}

    with pytest.raises(EstimateError, match=r"the last cheap run's judge cost is unknown; add its model to \[prices\]"):
        estimate(unknown, price=(3, 15), planned_generations=150)


@pytest.mark.parametrize(("spent", "cap", "stop"), [(1.90, 2.00, True), (1.70, 2.00, False), (5.00, None, False)])
def test_stop_for_cap_counts_the_held_back_reserve(spent: float, cap: float | None, stop: bool) -> None:
    assert stop_for_cap(spent, reserve=0.20, cap=cap) is stop


def test_stuck_reasons_names_a_check_that_never_passed_and_two_that_never_pass_together() -> None:
    records = [
        (0, "A", {"length": ["too long"], "x": [], "y": []}),
        (1, "A", {"length": ["too long"], "x": [], "y": []}),
        (0, "B", {"length": [], "x": ["no"], "y": []}),
        (1, "B", {"length": [], "x": [], "y": ["no"]}),
    ]

    assert stuck_reasons(records) == [
        "length never passed on case A in any version: this needs more input data or a different model",
        "x and y never passed together on case B: these two rules may conflict",
    ]


def test_stuck_reasons_is_empty_when_every_check_passed_somewhere_together() -> None:
    records = [(0, "A", {"x": ["no"], "y": []}), (1, "A", {"x": [], "y": []})]

    assert stuck_reasons(records) == []


def test_progress_line() -> None:
    assert progress_line(version=3, passing=17, total=20, best=True) == "version 3: 17 of 20 checks passing on selection cases (best so far)"
    assert progress_line(version=4, passing=15, total=20, best=False) == "version 4: 15 of 20 checks passing on selection cases"
