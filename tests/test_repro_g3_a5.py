from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeModel
from tests.test_check_cli import make_suite
from whetstone.entry.cli import run
from whetstone.platform.model import ModelError


def test_a_mistyped_model_fails_on_the_first_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_suite(tmp_path, {"a": "Rest today.", "b": "Walk later.", "c": "Sleep early."})

    def answer(request: dict[str, Any]) -> str:
        if request["model"] == "modle-b":
            raise ModelError("NotFoundError 404")
        return "Rest today."

    model = FakeModel(answer)
    monkeypatch.chdir(tmp_path)

    code = run(["baseline", "daily", "--models", "modle-b"], make_model=lambda _settings: model)

    assert code == 2
    assert "modle-b failed on case a: NotFoundError 404" in capsys.readouterr().err
    assert [r["model"] for r in model.requests] == ["fake-model", "modle-b"]  # one paid production call, not three
