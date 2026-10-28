import json
from pathlib import Path

import pytest

from tests.fakes import FakeModel, unused_model
from tests.test_check_cli import make_prompt, make_workspace
from whetstone.entry.cli import run


def harness_building(system: str) -> str:
    body = {"model": "fake-model", "system": system, "messages": [{"role": "user", "content": "Day 1."}]}
    return f"import json; print(json.dumps({body!r}))"


@pytest.mark.parametrize("table", ['[placeholders]\n"${VOICE}" = 3\n', 'placeholders = "x"\n'])
def test_a_placeholder_table_must_map_text_to_text(table: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_prompt(make_workspace(tmp_path), harness_building("Be brief."), {"first-day": {}})
    with (prompt / "prompt.toml").open("a") as toml:
        toml.write(table)
    monkeypatch.chdir(tmp_path)

    assert run(["check", "daily"], make_model=unused_model) == 2
    err = capsys.readouterr().err
    assert "prompt.toml" in err and "placeholders" in err
