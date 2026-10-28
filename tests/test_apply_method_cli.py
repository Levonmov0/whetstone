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
