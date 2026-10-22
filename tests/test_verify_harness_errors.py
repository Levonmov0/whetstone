from pathlib import Path

import pytest

from tests.fakes import unused_model
from tests.test_check_cli import ECHO_HARNESS, make_prompt, make_workspace
from whetstone.entry.cli import run


def test_unknown_case_exits_2_and_lists_the_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_prompt(make_workspace(tmp_path), ECHO_HARNESS, {"a": {"text": "Rest."}, "b": {"text": "Walk."}})
    (tmp_path / "expected.json").write_text("{}")
    monkeypatch.chdir(tmp_path)

    code = run(["verify-harness", "daily", "--case", "typo", "--expected", "expected.json"], make_model=unused_model)

    assert code == 2
    assert "no case named typo; cases: a, b" in capsys.readouterr().err


@pytest.mark.parametrize("contents", [None, "{not json"])
def test_unreadable_expected_file_exits_2(
    contents: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_prompt(make_workspace(tmp_path), ECHO_HARNESS, {"a": {"text": "Rest."}})
    if contents is not None:
        (tmp_path / "expected.json").write_text(contents)
    monkeypatch.chdir(tmp_path)

    code = run(["verify-harness", "daily", "--case", "a", "--expected", "expected.json"], make_model=unused_model)

    assert code == 2
    assert "can't read the production request in expected.json" in capsys.readouterr().err
