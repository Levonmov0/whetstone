from pathlib import Path

import pytest

from tests.fakes import unused_model
from tests.test_check_cli import make_prompt, make_workspace
from whetstone.entry.cli import run


def sourced_prompt(root: Path, source_text: str) -> Path:
    """A workspace in root/whetstone whose editable part, "Be brief.", comes from root/src/prompt.txt."""
    prompt = make_prompt(make_workspace(root / "whetstone"), "", {})
    (root / "src").mkdir()
    (root / "src" / "prompt.txt").write_text(source_text)
    with (prompt / "prompt.toml").open("a") as toml:
        toml.write('source = "../src/prompt.txt"\n')
    return prompt


def test_text_found_once_in_the_source_is_applied_exactly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = sourced_prompt(tmp_path, "PROMPT = `Be brief.`\n")
    before = (prompt / "prompt.toml").read_text()
    monkeypatch.chdir(tmp_path / "whetstone")

    assert run(["apply-method", "daily"], make_model=unused_model) == 0
    assert capsys.readouterr().out.splitlines()[0] == "exact"
    assert (prompt / "prompt.toml").read_text() == before


@pytest.mark.parametrize(("source_text", "times"), [("PROMPT = [`Be`, `brief.`].join(' ')\n", 0), ("A = `Be brief.`\nB = `Be brief.`\n", 2)])
def test_text_not_found_once_needs_a_code_edit(
    source_text: str, times: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sourced_prompt(tmp_path, source_text)
    monkeypatch.chdir(tmp_path / "whetstone")

    assert run(["apply-method", "daily"], make_model=unused_model) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "code-edit"
    assert f"found {times} times in ../src/prompt.txt" in out


@pytest.mark.parametrize(
    ("breakage", "message"),
    [("no source", 'has no "source"'), ("source missing", "../src/prompt.txt"), ("no editable", "editable.txt")],
)
def test_apply_method_needs_a_source_and_an_editable_part(
    breakage: str, message: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompt = sourced_prompt(tmp_path, "PROMPT = `Be brief.`\n")
    if breakage == "no source":
        toml = prompt / "prompt.toml"
        toml.write_text(toml.read_text().replace('source = "../src/prompt.txt"\n', ""))
    elif breakage == "source missing":
        (tmp_path / "src" / "prompt.txt").unlink()
    else:
        (prompt / "editable.txt").unlink()
    monkeypatch.chdir(tmp_path / "whetstone")

    assert run(["apply-method", "daily"], make_model=unused_model) == 2
    assert message in capsys.readouterr().err
