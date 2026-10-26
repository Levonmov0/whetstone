import json
from pathlib import Path

import pytest

from tests.test_check_cli import echo_model, make_suite
from whetstone.entry.cli import run


def test_proposed_cases_never_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    (prompt / "cases" / "proposed").mkdir()
    (prompt / "cases" / "proposed" / "b.json").write_text(json.dumps({"text": "Walk later."}))
    model = echo_model()
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: model)

    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert "PASS a" in out
    assert not any("b" in line.split() for line in out)
    assert len(model.requests) == 1
