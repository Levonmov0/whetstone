import json
from pathlib import Path

import pytest

from tests.fakes import unused_model
from tests.test_check_cli import ECHO_HARNESS, make_prompt, make_workspace
from whetstone.entry.cli import run

BUILT = {"model": "fake-model", "max_tokens": 50, "system": "Be brief.", "messages": [{"role": "user", "content": "Rest today."}]}


def verify(tmp_path: Path, expected: dict[str, object]) -> int:
    make_prompt(make_workspace(tmp_path), ECHO_HARNESS, {"a": {"text": "Rest today."}})
    (tmp_path / "expected.json").write_text(json.dumps(expected))
    return run(["verify-harness", "daily", "--case", "a", "--expected", str(tmp_path / "expected.json")], make_model=unused_model)


def test_matching_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)

    assert verify(tmp_path, BUILT) == 0
    assert "harness matches the production request" in capsys.readouterr().out


def test_differing_request_names_each_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)
    expected = {**BUILT, "max_tokens": 400, "messages": [{"role": "user", "content": "Rest today, Sam."}]}

    assert verify(tmp_path, expected) == 1
    out = capsys.readouterr().out.splitlines()
    assert "max_tokens differs" in out
    assert "messages[0].content differs" in out
