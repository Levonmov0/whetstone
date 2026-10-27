import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeModel
from tests.test_agreement_cli import RUBRIC_TAIL, swipes, write_labels
from tests.test_judges_cli import JUDGE_SETTINGS, judging
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
    toml = {"harness": f"{sys.executable} prompts/daily/harness.py", "provider": "anthropic", "model": "prod-model", "editable": "Be brief."}
    (prompt / "prompt.toml").write_text("".join(f"{k} = {json.dumps(v)}\n" for k, v in toml.items()))
    for i in range(cases):
        (prompt / "cases" / f"case-{i}.json").write_text(json.dumps({"text": f"Line {i}."}))
    return prompt


def writer() -> FakeModel:
    """Writes the case's line, running long unless the system prompt asks for short lines."""
    return FakeModel(lambda request: request["messages"][0]["content"] + ("" if "short" in request["system"] else " LONG"))


def rewriter(text: str = "Be brief. Keep it short.") -> FakeModel:
    """Answers every rewrite request with `text`, fenced the way GEPA reads a new instruction."""
    return FakeModel(lambda _request: f"```\n{text}\n```")


def start_run(model: FakeModel, rewrite: FakeModel, *extra: str, judge: Any = None) -> int:
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
    assert set(json.loads((folder / "cost.json").read_text())) == {"generation", "judge", "rewrite"}


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
    toml = (prompt / "prompt.toml").read_text().replace('"Be brief."', '"Be brief, {{name}}."')
    (prompt / "prompt.toml").write_text(toml)
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
