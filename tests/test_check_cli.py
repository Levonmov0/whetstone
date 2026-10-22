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
