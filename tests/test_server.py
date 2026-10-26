from pathlib import Path
from typing import Any

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


AUTH = {"Authorization": f"Bearer {TOKEN}"}


def card_ids(response: Any) -> list[str]:
    return [c["case_id"] for c in response.json()["cards"]]


def test_cards_come_with_input_output_and_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = graded_suite(tmp_path, monkeypatch)

    response = client.get("/api/cards", headers={**AUTH, "X-Grader": "Levon"})

    assert response.status_code == 200
    body = response.json()
    assert [(c["case_id"], c["input"], c["output"], c["caught_by"]) for c in body["cards"]] == [
        ("a", {"text": "Rest today."}, "Rest today.", []),
        ("b", {"text": "Your HRV is low."}, "Your HRV is low.", ["banned"]),
    ]
    assert all(c["card_id"].endswith(f":{c['case_id']}") for c in body["cards"])
    assert body["reasons"] == []


def test_reason_chips_come_from_prompt_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    with (prompt / "prompt.toml").open("a") as f:
        f.write('reasons = ["too long", "wrong voice"]\n')
    monkeypatch.chdir(tmp_path)
    run(["check", "daily"], make_model=lambda _settings: echo_model())
    client = TestClient(make_app(load_prompt(tmp_path, "daily"), TOKEN))

    assert client.get("/api/cards", headers={**AUTH, "X-Grader": "Levon"}).json()["reasons"] == ["too long", "wrong voice"]
