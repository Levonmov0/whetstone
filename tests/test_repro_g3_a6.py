from pathlib import Path

import pytest

from tests.test_check_cli import echo_model
from tests.test_judges_cli import judging, make_judged_suite
from whetstone.entry.cli import run


def test_one_judge_call_is_singular(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_judged_suite(tmp_path, {"a": "Rest today."})
    monkeypatch.chdir(tmp_path)

    run(["check", "daily"], make_model=lambda _settings: echo_model(), make_judge=lambda _workspace: judging("no"))

    assert capsys.readouterr().out.splitlines()[0] == "1 generation call and 1 judge call"
