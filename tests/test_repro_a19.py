import json
import subprocess
import sys
from pathlib import Path

from tests.test_check_cli import make_workspace
from whetstone.entry.cli import stop_server

IGNORES_SIGTERM = "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\nprint('ready', flush=True)\ntime.sleep(60)\n"


def test_state_is_kept_while_the_server_still_runs(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    (workspace / ".whetstone").mkdir()
    # Its command line names the server module and workspace, as a real server's does.
    server = subprocess.Popen(
        [sys.executable, "-c", IGNORES_SIGTERM, "whetstone.entry.serve_main", str(workspace)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert server.stdout and server.stdout.readline() == "ready\n"
        state_file = workspace / ".whetstone" / "serve.json"
        state_file.write_text(json.dumps({"pid": server.pid, "host": "127.0.0.1", "port": 1, "prompt": "daily", "token": "t", "url": "u"}))

        stop_server(workspace)

        assert server.poll() is not None or state_file.exists(), "serve.json was deleted while the server still runs"
    finally:
        server.kill()
        server.wait()
