import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.test_check_cli import echo_model, make_suite
from whetstone.entry.cli import run
from whetstone.entry.server import make_app
from whetstone.features.workspace.load import load_prompt


def test_the_server_stops_at_its_lifetime_whatever_graders_do(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_suite(tmp_path, {"a": "Rest today."})
    monkeypatch.chdir(tmp_path)
    run(["check", "daily"], make_model=lambda _settings: echo_model())
    stopped = threading.Event()
    app = make_app(load_prompt(tmp_path, "daily"), "t", lifetime=timedelta(seconds=0.5), on_expiry=stopped.set)

    with TestClient(app) as client:
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline and not stopped.is_set():
            client.get("/api/cards", headers={"Authorization": "Bearer t", "X-Grader": "Levon"})  # an open app in use
            time.sleep(0.1)

    # spec, open question 1: a fixed lifetime from start; nothing resets the clock
    assert stopped.is_set()
