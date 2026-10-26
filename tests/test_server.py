from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.test_check_cli import echo_model, make_suite
from whetstone.entry.cli import run
from whetstone.entry.server import make_app
from whetstone.features.workspace.load import load_prompt

TOKEN = "t0ken-for-tests"


def graded_suite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    make_suite(tmp_path, {"a": "Rest today.", "b": "Your HRV is low."})
    monkeypatch.chdir(tmp_path)
    run(["check", "daily"], make_model=lambda _settings: echo_model())
    return TestClient(make_app(load_prompt(tmp_path, "daily"), TOKEN))


@pytest.mark.parametrize(
    ("method", "path", "headers"),
    [
        ("GET", "/api/cards", {}),
        ("GET", "/api/cards", {"Authorization": "Bearer wrong"}),
        ("POST", "/api/swipes", {}),
    ],
)
def test_requests_without_the_token_are_rejected(
    method: str, path: str, headers: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = graded_suite(tmp_path, monkeypatch)

    response = client.request(method, path, headers={"X-Grader": "Levon", **headers}, json={})

    assert response.status_code == 401
    assert response.json() == {"error": "missing or wrong token"}
