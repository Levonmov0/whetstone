import fcntl
import json
import random
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeModel, unused_model
from tests.test_agreement_cli import RUBRIC_TAIL, swipes, write_labels
from tests.test_judges_cli import JUDGE_SETTINGS, add_private_case, judging
from whetstone.entry.cli import run
from whetstone.features.optimize.core import split_cases
from whetstone.platform.model import ModelError

HARNESS = (
    "import json, sys\n"
    "case = json.load(sys.stdin)\n"
    'print(json.dumps({"model": "prod-model", "max_tokens": 50, "system": "Be brief.", "messages": [{"role": "user", "content": case["text"]}]}))\n'
)
SHORT_CHECK = 'def check(output):\n    return ["Runs long."] if "LONG" in output else []\n'


def make_run_suite(workspace: Path, cases: int = 10, settings: str = "") -> Path:
    """A prompt whose editable part is "Be brief.", with one check that fails outputs saying LONG."""
    (workspace / "whetstone.toml").write_text(settings)
    prompt = workspace / "prompts" / "daily"
    (prompt / "cases").mkdir(parents=True)
    (prompt / "checks").mkdir()
    (prompt / "harness.py").write_text(HARNESS)
    (prompt / "checks" / "short.py").write_text(SHORT_CHECK)
    toml = {"harness": f"{sys.executable} prompts/daily/harness.py", "provider": "anthropic", "model": "prod-model"}
    (prompt / "prompt.toml").write_text("".join(f"{k} = {json.dumps(v)}\n" for k, v in toml.items()))
    (prompt / "editable.txt").write_text("Be brief.")
    for i in range(cases):
        (prompt / "cases" / f"case-{i}.json").write_text(json.dumps({"text": f"Line {i}."}))
    return prompt


def writer() -> FakeModel:
    """Writes the case's line, running long unless the system prompt asks for short lines."""
    return FakeModel(lambda request: request["messages"][0]["content"] + ("" if "short" in request["system"] else " LONG"))


def rewriter(text: str = "Be brief. Keep it short.") -> FakeModel:
    """Answers every rewrite request with `text`, fenced the way GEPA reads a new instruction."""
    return FakeModel(lambda _request: f"```\n{text}\n```")


def start_run(model: FakeModel, rewrite: FakeModel, *extra: str, judge: Callable[[Path], FakeModel] | None = None) -> int:
    argv = ["run", "daily", "--model", "cheap-model", "--budget", "30", "--foreground", *extra]
    return run(argv, make_model=lambda _settings: model, make_judge=judge, make_rewrite=lambda _workspace: rewrite)


def run_folder(prompt: Path) -> Path:
    [folder] = (prompt / "runs").glob("run-*")
    return folder


def test_a_run_drives_gepa_to_a_better_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_run_suite(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = start_run(writer(), rewriter())

    assert code == 0
    folder = run_folder(prompt)
    assert "short" in (folder / "candidate.txt").read_text()
    assert (folder / "report.md").is_file()
    assert set(json.loads((folder / "cost.json").read_text())) == {"generation", "judge", "rewrite", "gate"}


def test_held_back_cases_never_reach_gepa(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_run_suite(tmp_path)
    model, rewrite = writer(), rewriter()
    monkeypatch.chdir(tmp_path)

    start_run(model, rewrite)

    split = json.loads((run_folder(prompt) / "split.json").read_text())
    assert sorted(split) == ["held_back", "selection", "training"]
    assert sorted(split["training"] + split["selection"] + split["held_back"]) == sorted(f"case-{i}" for i in range(10))
    held = {f"Line {case_id.removeprefix('case-')}." for case_id in split["held_back"]}
    assert not any(text in json.dumps(request) for request in rewrite.requests for text in held)
    is_held = [request["messages"][0]["content"] in held for request in model.requests]
    assert True in is_held
    assert is_held.index(True) > max(i for i, h in enumerate(is_held) if not h)


BLOCKS_HARNESS = (
    "import json, sys\n"
    "case = json.load(sys.stdin)\n"
    'print(json.dumps({"model": "prod-model", "max_tokens": 50, "tools": [{"name": "t"}], '
    '"messages": [{"role": "user", "content": [{"type": "text", "text": "Be brief."}, {"type": "text", "text": case["text"]}]}]}))\n'
)


def test_each_generation_is_the_production_request_with_only_model_and_editable_swapped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_run_suite(tmp_path)
    (prompt / "harness.py").write_text(BLOCKS_HARNESS)
    model = FakeModel(lambda request: request["messages"][0]["content"][1]["text"] + ("" if "short" in json.dumps(request) else " LONG"))
    monkeypatch.chdir(tmp_path)

    start_run(model, rewriter())

    texts = {"Be brief.", "Be brief. Keep it short."}
    for request in model.requests:
        [instruction, line] = request["messages"][0]["content"]
        assert instruction["text"] in texts
        expected = {"model": "cheap-model", "max_tokens": 50, "tools": [{"name": "t"}], "messages": [{"role": "user", "content": [instruction, line]}]}
        assert request == expected
    assert {r["messages"][0]["content"][0]["text"] for r in model.requests} == texts


def test_a_run_with_no_new_version_fails_loudly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_run_suite(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = start_run(writer(), rewriter("Be brief."))

    assert code == 1
    assert "GEPA produced no new version" in capsys.readouterr().out
    assert not list((prompt / "runs").glob("run-*/candidate.txt"))


def test_a_run_whose_rewrites_all_fail_says_why(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_run_suite(tmp_path)
    monkeypatch.chdir(tmp_path)

    def broken(_request: dict[str, Any]) -> str:
        raise ModelError("claude failed: Not logged in")

    code = start_run(writer(), FakeModel(broken))

    out = capsys.readouterr().out
    assert code == 1
    assert "GEPA produced no new version" in out and "claude failed: Not logged in" in out


def test_new_versions_that_never_beat_the_original_on_selection_fail_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompt = make_run_suite(tmp_path)
    train, _select, _held = split_cases([f"case-{i}" for i in range(10)])
    trained = {f"Line {case_id.removeprefix('case-')}." for case_id in train}
    # Short lines only on training cases: GEPA keeps the rewrite, but it does no better on the selection cases.
    model = FakeModel(lambda r: r["messages"][0]["content"] + ("" if "short" in r["system"] and r["messages"][0]["content"] in trained else " LONG"))
    monkeypatch.chdir(tmp_path)

    code = start_run(model, rewriter())

    assert code == 1
    assert "no new version beat the original on the selection cases" in capsys.readouterr().out
    assert not list((prompt / "runs").glob("run-*/candidate.txt"))


def test_a_rewrite_that_drops_a_placeholder_is_never_generated_and_never_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_run_suite(tmp_path)
    (prompt / "harness.py").write_text(HARNESS.replace("Be brief.", "Be brief, {{name}}."))
    (prompt / "editable.txt").write_text("Be brief, {{name}}.")
    model = writer()
    monkeypatch.chdir(tmp_path)

    code = start_run(model, rewriter("Be brief. Keep it short."))

    assert code == 1
    assert all(request["system"] == "Be brief, {{name}}." for request in model.requests)


def judged_run_suite(workspace: Path, good_failed: int) -> Path:
    """A run suite with the "assumes" judge, swiped so it fails `good_failed` of 10 good cards and all 5 bad ones."""
    prompt = make_run_suite(workspace, settings=JUDGE_SETTINGS)
    (prompt / "checks" / "assumes.judge.toml").write_text('reasons = ["assumes the outcome"]\n' + RUBRIC_TAIL)
    write_labels(prompt / "labels.jsonl", swipes(good_failed))
    return prompt


@pytest.mark.parametrize("good_failed", [3])
def test_an_untrusted_judge_stops_the_run_before_any_generation(
    good_failed: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    judged_run_suite(tmp_path, good_failed)
    model = writer()
    monkeypatch.chdir(tmp_path)

    code = start_run(model, rewriter(), judge=lambda _workspace: judging("yes"))

    assert code == 2
    assert "assumes: fails outputs Levon called good (70%); sharpen the rubric" in capsys.readouterr().err
    assert model.requests == []


def test_a_warned_judge_is_shown_and_the_run_goes_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    judged_run_suite(tmp_path, good_failed=2)
    monkeypatch.chdir(tmp_path)

    code = start_run(writer(), rewriter(), judge=lambda _workspace: judging("yes"))

    assert code == 0
    assert "assumes: agrees with Levon on 80% of good cards; below 90% is a warning" in capsys.readouterr().out


def test_a_run_needs_three_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_run_suite(tmp_path, cases=2)
    model = writer()
    monkeypatch.chdir(tmp_path)

    code = start_run(model, rewriter())

    assert code == 2
    assert "a run needs at least 3 cases; this prompt has 2" in capsys.readouterr().err
    assert model.requests == []


def test_the_cost_record_prices_each_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_run_suite(tmp_path, settings='[prices]\n"cheap-model" = [1, 5]\n')
    model, rewrite = writer(), FakeModel(lambda _r: "```\nBe brief. Keep it short.\n```", cost_usd=0.05)
    monkeypatch.chdir(tmp_path)

    start_run(model, rewrite)

    cost = json.loads((run_folder(prompt) / "cost.json").read_text())
    calls = len(model.requests)
    assert cost["generation"] == {"calls": calls, "input_tokens": 10 * calls, "output_tokens": 5 * calls, "dollars": pytest.approx(calls * 35e-6)}
    assert cost["rewrite"]["calls"] == len(rewrite.requests) and cost["rewrite"]["dollars"] == pytest.approx(0.05 * len(rewrite.requests))
    assert cost["judge"] == {"calls": 0, "input_tokens": 0, "output_tokens": 0, "dollars": 0.0}


def test_a_model_without_a_price_costs_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_run_suite(tmp_path)
    monkeypatch.chdir(tmp_path)

    start_run(writer(), rewriter())

    assert json.loads((run_folder(prompt) / "cost.json").read_text())["generation"]["dollars"] is None
    assert "$ unknown" in (run_folder(prompt) / "report.md").read_text()


def test_a_bad_prices_table_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_run_suite(tmp_path, settings='[prices]\n"cheap-model" = "cheap"\n')
    monkeypatch.chdir(tmp_path)

    code = start_run(writer(), rewriter())

    assert code == 2
    assert "[prices] maps each model to [input, output] dollars per million tokens" in capsys.readouterr().err


def test_progress_is_shown_as_versions_are_scored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_run_suite(tmp_path)
    monkeypatch.chdir(tmp_path)

    start_run(writer(), rewriter())

    out = capsys.readouterr().out.splitlines()
    assert "version 1: 0 of 3 checks passing on selection cases (best so far)" in out
    assert "version 2: 3 of 3 checks passing on selection cases (best so far)" in out


def test_the_report_compares_held_back_results_and_explains_a_stuck_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_run_suite(tmp_path)
    _train, select, _held = split_cases([f"case-{i}" for i in range(10)])
    stuck = f"Line {select[0].removeprefix('case-')}."
    (prompt / "checks" / "stuck.py").write_text(f"def check(output):\n    return ['Always wrong.'] if output.startswith({stuck!r}) else []\n")
    monkeypatch.chdir(tmp_path)

    start_run(writer(), rewriter())

    lines = (run_folder(prompt) / "report.md").read_text().splitlines()
    assert "| version | every check | average score | short | stuck |" in lines
    assert any(line.startswith("| original | 0/4 |") for line in lines)
    assert any(line.startswith("| candidate | 4/4 |") for line in lines)
    assert "Rules now passing on every held-back case: short" in lines
    assert "Length: +167% (9 → 24 chars)" in lines
    assert "+Be brief. Keep it short." in lines
    assert "## Cost" in lines
    assert f"- stuck never passed on case {select[0]} in any version: this needs more input data or a different model" in lines


def test_the_held_back_outputs_become_a_blind_deck(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_run_suite(tmp_path)
    random.seed(3)
    monkeypatch.chdir(tmp_path)

    start_run(writer(), rewriter())

    folder = run_folder(prompt)
    deck = json.loads((tmp_path / ".whetstone" / "decks" / "daily.json").read_text())
    assert folder.name == f"run-{deck['id']}"
    held = json.loads((folder / "split.json").read_text())["held_back"]
    ids = [card["card_id"] for card in deck["cards"]]
    assert len(set(ids)) == 8
    assert all(re.fullmatch(rf"{deck['id']}:case-\d:[0-9a-f]{{8}}", card_id) and card_id.split(":")[1] in held for card_id in ids)
    versions = json.loads((folder / "cards.json").read_text())
    assert versions == {card["card_id"].rsplit(":", 1)[1]: "original" if "LONG" in card["output"] else "candidate" for card in deck["cards"]}
    assert "original" not in json.dumps(deck["cards"]) and "candidate" not in json.dumps(deck["cards"])
    order = ["LONG" in card["output"] for card in deck["cards"]]
    assert order not in ([True] * 4 + [False] * 4, [False] * 4 + [True] * 4)


def test_the_report_adds_the_blind_swipes_per_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_run_suite(tmp_path)
    monkeypatch.chdir(tmp_path)
    start_run(writer(), rewriter())
    deck = json.loads((tmp_path / ".whetstone" / "decks" / "daily.json").read_text())
    labels: list[dict[str, Any]] = [
        {"card_id": card["card_id"], "case_id": card["case_id"], "grader": "Levon", "at": f"2026-10-27T10:00:0{i}",
         "verdict": "bad" if "LONG" in card["output"] else "good", "reasons": [], "note": ""}
        for i, card in enumerate(deck["cards"])
    ]  # fmt: skip
    labels[0] = {**labels[0], "verdict": "skip"}
    (prompt / "labels.jsonl").write_text("".join(json.dumps(label) + "\n" for label in labels))
    skipped = "original" if "LONG" in deck["cards"][0]["output"] else "candidate"

    code = run(["run", "daily", "--report"], make_model=unused_model)

    assert code == 0
    lines = (run_folder(prompt) / "report.md").read_text().splitlines()
    assert lines[lines.index("## Swipes") :] == [
        "## Swipes",
        "",
        "- original: good 0, bad " + ("3, skip 1" if skipped == "original" else "4, skip 0"),
        "- candidate: good " + ("3, bad 0, skip 1" if skipped == "candidate" else "4, bad 0, skip 0"),
    ]


def test_the_report_needs_a_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_run_suite(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = run(["run", "daily", "--report"], make_model=unused_model)

    assert code == 2
    assert "no run of daily yet; run whetstone run daily --model …" in capsys.readouterr().err


def test_a_run_needs_a_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_run_suite(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = run(["run", "daily"], make_model=unused_model)

    assert code == 2
    assert "pass --model <a cheap model>, or --production" in capsys.readouterr().err


def test_a_run_on_real_data_keeps_its_folder_out_of_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_run_suite(tmp_path, settings='repo_providers = ["anthropic"]\n')
    add_private_case(prompt)
    monkeypatch.chdir(tmp_path)

    code = start_run(writer(), rewriter())

    assert code == 0
    assert (run_folder(prompt) / ".gitignore").read_text() == "*\n"


def test_real_data_never_goes_to_a_provider_the_repo_does_not_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompt = make_run_suite(tmp_path, settings='repo_providers = ["openai"]\n')
    add_private_case(prompt)
    rewrite = rewriter()
    monkeypatch.chdir(tmp_path)

    code = start_run(writer(), rewrite)

    assert code == 2
    assert "real-data cases go only to providers this repo already uses (openai); anthropic is not one" in capsys.readouterr().err
    assert rewrite.requests == []


def test_a_run_without_real_data_can_be_committed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_run_suite(tmp_path)
    monkeypatch.chdir(tmp_path)

    start_run(writer(), rewriter())

    assert not (run_folder(prompt) / ".gitignore").exists()


PROD_PRICES = '[prices]\n"prod-model" = [3, 15]\n"cheap-model" = [1, 5]\n'
CHEAP_COST = {
    "generation": {"calls": 100, "input_tokens": 100_000, "output_tokens": 10_000, "dollars": 0.15},
    "judge": {"calls": 100, "input_tokens": 50_000, "output_tokens": 1_000, "dollars": 0.20},
    "rewrite": {"calls": 10, "input_tokens": 40_000, "output_tokens": 8_000, "dollars": 0.50},
}


def cheap_run_with_known_cost(prompt: Path) -> None:
    """A real cheap run, its cost record then replaced with round numbers."""
    start_run(writer(), rewriter())
    (run_folder(prompt) / "cost.json").write_text(json.dumps(CHEAP_COST))


def test_a_production_run_shows_its_estimate_and_waits_for_a_yes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_run_suite(tmp_path, settings=PROD_PRICES)
    monkeypatch.chdir(tmp_path)
    cheap_run_with_known_cost(prompt)
    capsys.readouterr()
    model, rewrite = writer(), rewriter()

    # 92 GEPA generations and 2 x 4 held-back ones: 100 at the production price, and the cheap run's judges and rewrites
    code = run(["run", "daily", "--production", "--budget", "92"], make_model=lambda _s: model, make_rewrite=lambda _w: rewrite)

    assert code == 0
    assert "a production run on prod-model: about $1.15; it stops at $2.30. Rerun with --yes to start." in capsys.readouterr().out
    assert model.requests == [] and rewrite.requests == []


def test_a_production_run_needs_a_cheap_run_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_run_suite(tmp_path, settings=PROD_PRICES)
    monkeypatch.chdir(tmp_path)

    code = run(["run", "daily", "--production"], make_model=unused_model)

    assert code == 2
    assert "run a cheap run first: whetstone run daily --model <a cheap model>" in capsys.readouterr().err


def test_a_production_run_needs_the_production_price(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_run_suite(tmp_path, settings='[prices]\n"cheap-model" = [1, 5]\n')
    monkeypatch.chdir(tmp_path)
    cheap_run_with_known_cost(prompt)

    code = run(["run", "daily", "--production"], make_model=unused_model)

    assert code == 2
    assert "[prices] in whetstone.toml has no price for prod-model; a production run needs one to estimate its cost" in capsys.readouterr().err


def test_a_production_estimate_needs_the_cheap_runs_dollars(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_run_suite(tmp_path, settings=PROD_PRICES)
    monkeypatch.chdir(tmp_path)
    cheap_run_with_known_cost(prompt)
    cost = json.loads((run_folder(prompt) / "cost.json").read_text())
    (run_folder(prompt) / "cost.json").write_text(json.dumps(cost | {"rewrite": cost["rewrite"] | {"dollars": None}}))

    code = run(["run", "daily", "--production"], make_model=unused_model)

    assert code == 2
    assert "the last cheap run's rewrite cost is unknown; add its model to [prices]" in capsys.readouterr().err


def test_a_production_run_stops_at_twice_the_estimate_and_keeps_the_best_so_far(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A generation costs $0.105 at these prices (10 input and 5 output tokens); a rewrite reports $1.
    prompt = make_run_suite(tmp_path, settings='[prices]\n"prod-model" = [3000, 15000]\n')
    monkeypatch.chdir(tmp_path)
    cheap_run_with_known_cost(prompt)
    # 30 GEPA generations and 8 held-back ones, as many as the cheap run made, at no cost, and $2.50 of rewrites: $2.50 in all.
    free = {"calls": 38, "input_tokens": 0, "output_tokens": 0, "dollars": 0.0}
    (run_folder(prompt) / "cost.json").write_text(json.dumps({"generation": free, "judge": free | {"calls": 0}, "rewrite": free | {"calls": 1, "dollars": 2.5}}))
    model, rewrite = writer(), FakeModel(lambda _r: "```\nBe brief. Keep it short.\n```", cost_usd=1.0)
    capsys.readouterr()

    code = run(["run", "daily", "--production", "--yes", "--budget", "30", "--foreground"], make_model=lambda _s: model, make_rewrite=lambda _w: rewrite)

    assert code == 0
    assert "a production run on prod-model: about $2.50; it stops at $5.00." in capsys.readouterr().out
    assert {request["model"] for request in model.requests} == {"prod-model"}
    assert len(model.requests) < 38
    [folder] = [f for f in (prompt / "runs").glob("run-*") if json.loads((f / "run.json").read_text())["model"] == "prod-model"]
    assert "Stopped at the cap ($5.00): the best version so far is the candidate." in (folder / "report.md").read_text()
    assert "short" in (folder / "candidate.txt").read_text()
    assert sum(cost["dollars"] for cost in json.loads((folder / "cost.json").read_text()).values()) <= 5.00


@pytest.mark.parametrize("where", [["--foreground"], []])
def test_one_run_per_prompt_at_a_time(where: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_run_suite(tmp_path)
    model = writer()
    (tmp_path / ".whetstone" / "runs").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    with (tmp_path / ".whetstone" / "runs" / "daily.lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)  # a run of daily going on
        code = run(["run", "daily", "--model", "cheap-model", *where], make_model=lambda _s: model, make_rewrite=lambda _w: rewriter())

    assert code == 2
    assert "a run of daily is already going; its log is in .whetstone/runs/" in capsys.readouterr().err
    assert model.requests == []


def test_a_failed_run_still_records_what_it_cost(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_run_suite(tmp_path)
    monkeypatch.chdir(tmp_path)
    start_run(writer(), rewriter())  # a run with a candidate
    model = writer()

    code = start_run(model, rewriter("Be brief."))

    assert code == 1
    [failed] = [f for f in (prompt / "runs").glob("run-*") if not (f / "candidate.txt").exists()]
    assert json.loads((failed / "cost.json").read_text())["generation"]["calls"] == len(model.requests)
    assert "GEPA produced no new version" in (failed / "report.md").read_text()
    assert run(["run", "daily", "--report"], make_model=unused_model) == 0


def test_an_empty_rewrite_is_rejected_without_a_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_run_suite(tmp_path)
    model = writer()
    monkeypatch.chdir(tmp_path)

    code = start_run(model, FakeModel(lambda _r: "```\n\n```"))

    assert code == 1
    assert "GEPA produced no new version" in capsys.readouterr().out
    assert all(request["system"] == "Be brief." for request in model.requests)


def test_the_judge_gate_is_counted_apart_from_the_runs_judging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = judged_run_suite(tmp_path, good_failed=0)
    model = writer()
    monkeypatch.chdir(tmp_path)

    start_run(model, rewriter(), judge=lambda _workspace: judging("yes"))

    cost = json.loads((run_folder(prompt) / "cost.json").read_text())
    assert cost["gate"]["calls"] == 15  # each swiped card once
    assert cost["judge"]["calls"] == len(model.requests)  # one judge call per output


@pytest.mark.parametrize(
    ("settings", "unpriced"),
    [
        ('[models]\nrewrite = { via = "api", model = "rewrite-model" }\n', "rewrite-model"),
        ('[models]\njudge = { provider = "openai", model = "judge-model" }\n', "judge-model"),
    ],
)
def test_a_production_run_needs_a_price_for_every_model_it_pays_by_the_token(
    settings: str, unpriced: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompt = make_run_suite(tmp_path, settings=PROD_PRICES)
    monkeypatch.chdir(tmp_path)
    cheap_run_with_known_cost(prompt)
    (tmp_path / "whetstone.toml").write_text(settings + PROD_PRICES)
    if "judge" in settings:
        (prompt / "checks" / "assumes.judge.toml").write_text(RUBRIC_TAIL)

    code = run(["run", "daily", "--production"], make_model=unused_model)

    assert code == 2
    assert f"[prices] in whetstone.toml has no price for {unpriced}; a production run needs one to estimate its cost" in capsys.readouterr().err


def test_a_run_stopped_partway_still_records_what_it_cost(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_run_suite(tmp_path)
    (prompt / "checks" / "crashes.py").write_text('def check(output):\n    if output.endswith("short."):\n        raise ValueError("boom")\n    return []\n')
    model = FakeModel(lambda r: r["messages"][0]["content"] + (" short." if "short" in r["system"] else " LONG"))
    monkeypatch.chdir(tmp_path)

    code = start_run(model, rewriter())

    assert code == 2
    assert "check crashes crashed on case" in capsys.readouterr().err
    folder = run_folder(prompt)
    assert json.loads((folder / "cost.json").read_text())["generation"]["calls"] == len(model.requests)
    assert "Stopped: check crashes crashed on case" in (folder / "report.md").read_text()


def test_a_failed_generation_stops_the_run_and_records_its_cost(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_run_suite(tmp_path)

    def flaky(request: dict[str, Any]) -> str:
        if "short" in request["system"]:
            raise ModelError("RateLimitError 429")
        return request["messages"][0]["content"] + " LONG"

    monkeypatch.chdir(tmp_path)

    code = start_run(FakeModel(flaky), rewriter())

    assert code == 2
    assert "cheap-model failed on case" in capsys.readouterr().err
    assert json.loads((run_folder(prompt) / "cost.json").read_text())["generation"]["calls"] > 0


def test_a_production_estimate_skips_a_cheap_run_with_no_cost_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_run_suite(tmp_path, settings=PROD_PRICES)
    monkeypatch.chdir(tmp_path)
    cheap_run_with_known_cost(prompt)
    killed = prompt / "runs" / "run-99991231T000000000000Z"  # a worker killed before it wrote its cost
    killed.mkdir()
    (killed / "run.json").write_text(json.dumps({"model": "cheap-model"}))
    capsys.readouterr()

    code = run(["run", "daily", "--production", "--budget", "92"], make_model=unused_model)

    assert code == 0
    assert "about $1.15" in capsys.readouterr().out


@pytest.mark.parametrize("setup", ["two cases", "bad prices", "untrusted judge"])
def test_a_background_start_vets_the_run_before_detaching(setup: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    if setup == "untrusted judge":
        judged_run_suite(tmp_path, good_failed=3)
    else:
        make_run_suite(tmp_path, cases=2 if setup == "two cases" else 10, settings='[prices]\n"m" = "cheap"\n' if setup == "bad prices" else "")
    monkeypatch.chdir(tmp_path)

    code = run(["run", "daily", "--model", "cheap-model"], make_model=lambda _s: writer(), make_judge=lambda _w: judging("yes"), make_rewrite=lambda _w: rewriter())

    assert code == 2
    assert "started in the background" not in capsys.readouterr().out
    assert not list((tmp_path / ".whetstone" / "runs").glob("*.log"))
