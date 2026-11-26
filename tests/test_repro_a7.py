from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.test_check_cli import echo_model, make_suite
from whetstone.entry.cli import run
from whetstone.entry.server import make_app
from whetstone.features.workspace.load import load_prompt

TOKEN = "t0ken-for-tests"


def test_a_deeply_nested_body_gets_400(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_suite(tmp_path, {"a": "Rest today."})
    monkeypatch.chdir(tmp_path)
    run(["check", "daily"], make_model=lambda _settings: echo_model())
    client = TestClient(make_app(load_prompt(tmp_path, "daily"), TOKEN), raise_server_exceptions=False)
    body = b"[" * 60_000  # under the 64 KB limit

    response = client.post("/api/swipes", headers={"Authorization": f"Bearer {TOKEN}"}, content=body)

    assert response.status_code == 400
