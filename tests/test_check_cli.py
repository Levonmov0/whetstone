from pathlib import Path

import pytest

from tests.fakes import unused_model
from whetstone.entry.cli import run


def test_no_workspace_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model)

    assert code == 2
    assert "no Whetstone workspace found; run /whetstone:init or pass --workspace" in capsys.readouterr().err
