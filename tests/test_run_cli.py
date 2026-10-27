import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeModel
from whetstone.entry.cli import run
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
