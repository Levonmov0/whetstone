from pathlib import Path

import pytest

from tests.test_baseline import by_model
from tests.test_check_cli import make_suite
from whetstone.entry.cli import run


def test_baseline_runs_a_model_listed_twice_only_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_suite(tmp_path, {"a": "Rest today."})
    model = by_model()
    monkeypatch.chdir(tmp_path)

    run(["baseline", "daily", "--models", "model-b,model-b"], make_model=lambda _settings: model)

    assert [r["model"] for r in model.requests] == ["fake-model", "model-b"]
