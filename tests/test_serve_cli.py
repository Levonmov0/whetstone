import fcntl
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

from tests.test_check_cli import echo_model, make_prompt_dir, make_suite
from whetstone.entry.cli import run
from whetstone.platform.network import TailscaleError, tailscale_address

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


def test_serving_again_shows_the_same_link(workspace: Path) -> None:
    first = serve(workspace, "daily", "--host", "127.0.0.1")
    pid = json.loads((workspace / ".whetstone" / "serve.json").read_text())["pid"]

    second = serve(workspace, "daily", "--host", "127.0.0.1")

    assert second.returncode == 0
    assert second.stdout == first.stdout
    assert json.loads((workspace / ".whetstone" / "serve.json").read_text())["pid"] == pid


def test_serving_another_prompt_while_one_runs_exits_2(workspace: Path) -> None:
    (make_prompt_dir(workspace, "other") / "prompt.toml").write_text((workspace / "prompts" / "daily" / "prompt.toml").read_text())
    serve(workspace, "daily", "--host", "127.0.0.1")

    result = serve(workspace, "other", "--host", "127.0.0.1")

    assert result.returncode == 2
    assert "already serving daily; run whetstone serve --stop first" in result.stderr


def test_a_stale_state_file_is_replaced(workspace: Path) -> None:
    dead = subprocess.Popen(["true"])
    dead.wait()
    (workspace / ".whetstone" / "serve.json").write_text(json.dumps({"pid": dead.pid, "host": "127.0.0.1", "port": 1, "prompt": "daily", "token": "old", "url": "old"}))

    result = serve(workspace, "daily", "--host", "127.0.0.1")

    assert result.returncode == 0
    assert "#t=old" not in result.stdout
    assert json.loads((workspace / ".whetstone" / "serve.json").read_text())["pid"] != dead.pid


def test_stop_ends_the_server(workspace: Path) -> None:
    serve(workspace, "daily", "--host", "127.0.0.1")
    port = json.loads((workspace / ".whetstone" / "serve.json").read_text())["port"]

    result = serve(workspace, "--stop")

    assert result.returncode == 0, result.stderr
    assert not (workspace / ".whetstone" / "serve.json").exists()
    with pytest.raises(httpx.ConnectError):
        httpx.get(f"http://127.0.0.1:{port}/")


def test_stop_with_nothing_running(workspace: Path) -> None:
    result = serve(workspace, "--stop")

    assert result.returncode == 0
    assert "no server running" in result.stdout


def set_access(workspace: Path, access: str) -> None:
    (workspace / "whetstone.toml").write_text(f'[phone]\naccess = "{access}"\n')


def test_lan_access_serves_on_the_lan_address(workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    set_access(workspace, "lan")
    monkeypatch.setattr("whetstone.entry.cli.lan_address", lambda: "127.0.0.1")  # stands in for the Wi-Fi address

    code = run(["serve", "daily"], make_model=lambda _settings: echo_model())

    assert code == 0
    assert "http://127.0.0.1:" in capsys.readouterr().out


def test_tailscale_access_serves_on_the_tailscale_address(
    workspace: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    set_access(workspace, "tailscale")
    bin_dir = tmp_path_factory.mktemp("bin")
    (bin_dir / "tailscale").write_text("#!/bin/sh\n[ \"$1 $2\" = 'ip -4' ] && echo 127.0.0.1\n")
    (bin_dir / "tailscale").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    code = run(["serve", "daily"], make_model=lambda _settings: echo_model())

    assert code == 0
    assert "http://127.0.0.1:" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("access", "error"),
    [("tailscale", "phone.access is tailscale but the tailscale command was not found"), ("tunnel", 'phone.access must be "lan" or "tailscale"')],
)
def test_bad_phone_access_exits_2(
    access: str, error: str, workspace: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    set_access(workspace, access)
    monkeypatch.setenv("PATH", str(tmp_path_factory.mktemp("empty")))

    code = run(["serve", "daily"], make_model=lambda _settings: echo_model())

    assert code == 2
    assert error in capsys.readouterr().err


def test_no_lan_address_says_to_pass_host(workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("whetstone.entry.cli.lan_address", lambda: None)

    code = run(["serve", "daily"], make_model=lambda _settings: echo_model())

    assert code == 2
    assert "no Wi-Fi or LAN address found; pass --host" in capsys.readouterr().err


def test_the_server_log_never_holds_the_token(workspace: Path) -> None:
    serve(workspace, "daily", "--host", "127.0.0.1")
    state = json.loads((workspace / ".whetstone" / "serve.json").read_text())
    httpx.get(f"http://127.0.0.1:{state['port']}/api/cards", headers={"Authorization": f"Bearer {state['token']}", "X-Grader": "Levon"})
    httpx.get(f"http://127.0.0.1:{state['port']}/api/cards", headers={"Authorization": "Bearer wrong"})

    log = (workspace / ".whetstone" / "server.log").read_text()

    assert "GET /api/cards" in log
    assert state["token"] not in log


def test_a_server_that_stops_itself_removes_its_state(workspace: Path) -> None:
    serve(workspace, "daily", "--host", "127.0.0.1")
    state_file = workspace / ".whetstone" / "serve.json"
    state = json.loads(state_file.read_text())
    httpx.get(f"http://127.0.0.1:{state['port']}/")  # answered: the server is up, not still starting

    os.kill(state["pid"], signal.SIGTERM)  # what the server does to itself at the end of its lifetime
    deadline = time.monotonic() + 5
    while state_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)

    assert not state_file.exists()


def test_a_corrupt_state_file_is_treated_as_stale(workspace: Path) -> None:
    private = workspace / ".whetstone"
    (private / "serve.json").write_text('{"pid": 1, "po')

    result = serve(workspace, "daily", "--host", "127.0.0.1")

    assert result.returncode == 0, result.stderr
    assert "http://127.0.0.1:" in result.stdout


def test_a_second_serve_waits_for_the_first(workspace: Path) -> None:
    private = workspace / ".whetstone"
    with (private / "serve.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # a first `serve` is mid-start
        second = subprocess.Popen([WHETSTONE, "serve", "daily", "--host", "127.0.0.1"], cwd=workspace, stdout=subprocess.PIPE, text=True)
        time.sleep(1)
        assert second.poll() is None and not (private / "serve.json").exists()
    assert second.wait(timeout=10) == 0
    assert (private / "serve.json").exists()


def test_serving_again_shows_the_link_even_when_the_address_changed(
    workspace: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = serve(workspace, "daily", "--host", "127.0.0.1")
    set_access(workspace, "tailscale")
    monkeypatch.setenv("PATH", str(tmp_path_factory.mktemp("empty")))

    second = subprocess.run([WHETSTONE, "serve", "daily"], cwd=workspace, capture_output=True, text=True, timeout=10)

    assert second.returncode == 0, second.stderr
    assert second.stdout == first.stdout


@pytest.mark.parametrize(
    ("host", "error"),
    [
        ("203.0.113.1", "can't listen on 203.0.113.1: "),
        ("0.0.0.0", "--host must be one address, not every interface (0.0.0.0)"),
        ("::", "--host must be one address, not every interface (::)"),
    ],
)
def test_an_unusable_host_exits_2(host: str, error: str, workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = run(["serve", "daily", "--host", host], make_model=lambda _settings: echo_model())

    assert code == 2
    assert error in capsys.readouterr().err
    assert not (workspace / ".whetstone" / "serve.json").exists()


def fake_tailscale(tmp_path_factory: pytest.TempPathFactory, script: str) -> str:
    bin_dir = tmp_path_factory.mktemp("bin")
    (bin_dir / "tailscale").write_text(f"#!/bin/sh\n{script}\n")
    (bin_dir / "tailscale").chmod(0o755)
    return str(bin_dir)


@pytest.mark.parametrize("script", ["echo 'Tailscale is stopped.' >&2; exit 1", "exit 0"])
def test_a_stopped_tailscale_exits_2(
    script: str, workspace: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    set_access(workspace, "tailscale")
    monkeypatch.setenv("PATH", f"{fake_tailscale(tmp_path_factory, script)}:{os.environ['PATH']}")

    code = run(["serve", "daily"], make_model=lambda _settings: echo_model())

    assert code == 2
    assert "tailscale is not connected" in capsys.readouterr().err


def test_tailscale_address_raises_its_own_error(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", fake_tailscale(tmp_path_factory, "echo 'Tailscale is stopped.' >&2; exit 1"))

    with pytest.raises(TailscaleError, match="Tailscale is stopped."):
        tailscale_address()
