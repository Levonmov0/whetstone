import json
import subprocess
import sys
from pathlib import Path


from tests.test_check_cli import make_workspace
from whetstone.entry.cli import stop_server

def test_stop_never_signals_a_process_that_is_not_the_server(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    (workspace / ".whetstone").mkdir()
    # The server stopped itself for idleness and the OS gave its pid to an unrelated process.
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        (workspace / ".whetstone" / "serve.json").write_text(
            json.dumps({"pid": other.pid, "host": "127.0.0.1", "port": 1, "prompt": "daily", "token": "old", "url": "old"})
        )

        stop_server(workspace)

        assert other.poll() is None, f"serve --stop killed an unrelated process (exit {other.returncode})"
    finally:
        other.kill()
        other.wait()
