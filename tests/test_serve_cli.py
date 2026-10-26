import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from tests.test_check_cli import echo_model, make_suite
from whetstone.entry.cli import run

WHETSTONE = str(Path(sys.executable).parent / "whetstone")


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    make_suite(tmp_path, {"a": "Rest today."})
    monkeypatch.chdir(tmp_path)
    run(["check", "daily"], make_model=lambda _settings: echo_model())
    yield tmp_path
    state = tmp_path / ".whetstone" / "serve.json"
    if state.is_file():  # never leave a server behind, whatever the test did
        try:
            os.kill(json.loads(state.read_text())["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass


def serve(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([WHETSTONE, "serve", *args], cwd=workspace, capture_output=True, text=True, timeout=10)


def test_serve_returns_and_the_server_outlives_it(workspace: Path) -> None:
    started = time.monotonic()
    result = serve(workspace, "daily", "--host", "127.0.0.1")

    assert result.returncode == 0, result.stderr
    assert time.monotonic() - started < 10
    url = re.search(r"http://127\.0\.0\.1:(\d+)/#t=(\S+)", result.stdout)
    assert url, result.stdout
    port, token = url.group(1), url.group(2)
    assert "█" in result.stdout or "▀" in result.stdout  # the QR code
    response = httpx.get(f"http://127.0.0.1:{port}/api/cards", headers={"Authorization": f"Bearer {token}", "X-Grader": "Levon"})
    assert response.status_code == 200
    state_file = workspace / ".whetstone" / "serve.json"
    state = json.loads(state_file.read_text())
    assert (state["port"], state["prompt"], state["token"]) == (int(port), "daily", token)
    assert os.getsid(state["pid"]) != os.getsid(0)
    assert stat.S_IMODE(state_file.stat().st_mode) == 0o600
