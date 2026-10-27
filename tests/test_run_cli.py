import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeModel
from whetstone.entry.cli import run

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
