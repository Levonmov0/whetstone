import json
import sys
from pathlib import Path

import pytest

from tests.fakes import unused_model
from whetstone.entry.cli import run


def test_no_workspace_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model)

    assert code == 2
    assert "no Whetstone workspace found; run /whetstone:init or pass --workspace" in capsys.readouterr().err


def make_prompt_dir(workspace: Path, name: str) -> Path:
    prompt = workspace / "prompts" / name
    prompt.mkdir(parents=True)
    return prompt


@pytest.mark.parametrize("layout", ["here", "subfolder", "flag"])
def test_unknown_prompt_lists_the_known_ones(
    layout: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = {"here": tmp_path, "subfolder": tmp_path / "whetstone", "flag": tmp_path / "elsewhere"}[layout]
    workspace.mkdir(exist_ok=True)
    (workspace / "whetstone.toml").write_text("")
    make_prompt_dir(workspace, "b")
    make_prompt_dir(workspace, "a")
    monkeypatch.chdir(tmp_path)
    argv = ["check", "daily"] + (["--workspace", str(workspace)] if layout == "flag" else [])

    code = run(argv, make_model=unused_model)

    assert code == 2
    assert "no prompt named daily; prompts: a, b" in capsys.readouterr().err


def make_workspace(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "whetstone.toml").write_text("")
    return root


def make_prompt(workspace: Path, harness: str, cases: dict[str, object], name: str = "daily", model: str = "fake-model") -> Path:
    """A prompt whose harness is the given Python source, run with this interpreter."""
    prompt = make_prompt_dir(workspace, name)
    (prompt / "harness.py").write_text(harness)
    settings = {
        "harness": f"{sys.executable} prompts/{name}/harness.py",
        "editable": "Be brief.",
        "provider": "anthropic",
        "model": model,
    }
    (prompt / "prompt.toml").write_text("".join(f"{k} = {json.dumps(v)}\n" for k, v in settings.items()))
    (prompt / "cases").mkdir()
    for case_id, case in cases.items():
        (prompt / "cases" / f"{case_id}.json").write_text(json.dumps(case))
    return prompt


@pytest.mark.parametrize(
    ("harness", "reason"),
    [
        ("import sys; print('builder exploded', file=sys.stderr); sys.exit(3)", "builder exploded"),
        ("print('not json')", "harness printed invalid JSON"),
    ],
)
def test_broken_harness_stops_before_any_model_call(
    harness: str, reason: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_prompt(make_workspace(tmp_path), harness, {"first-day": {"day": 1}})
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model)

    err = capsys.readouterr().err
    assert code == 2
    assert "first-day" in err
    assert reason in err


@pytest.mark.parametrize(
    ("request_body", "missing"),
    [
        ({"messages": [{"role": "user", "content": "Be brief."}]}, "model"),
        ({"model": "fake-model", "system": "Be brief."}, "messages"),
    ],
)
def test_request_missing_a_required_field(
    request_body: dict[str, object], missing: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_prompt(make_workspace(tmp_path), f"import json; print(json.dumps({request_body!r}))", {"first-day": {}})
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model)

    assert code == 2
    assert f'harness request for case first-day is missing "{missing}"' in capsys.readouterr().err
