import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.test_run_cli import make_run_suite

# Builds each case's request once; the second build of a case waits a second and fails, so the worker started in the
# background fails in its own way, after the command that started it has gone.
HARNESS = (
    "import json, sys, time\n"
    "from pathlib import Path\n"
    "case = json.load(sys.stdin)\n"
    "marker = Path('built-' + case['text'])\n"
    "if marker.exists():\n"
    "    time.sleep(1)\n"
    "    sys.exit(3)\n"
    "marker.touch()\n"
    'print(json.dumps({"model": "prod-model", "max_tokens": 50, "system": "Be brief.", "messages": [{"role": "user", "content": case["text"]}]}))\n'
)


def test_a_run_goes_on_in_the_background_after_its_session_ends(tmp_path: Path) -> None:
    prompt = make_run_suite(tmp_path, cases=3)
    (prompt / "harness.py").write_text(HARNESS)
    (tmp_path / ".env").write_text("GENERATION_API_KEY=never-used\n")
    command = [sys.executable, "-c", "from whetstone.entry.cli import main; main()", "run", "daily", "--model", "cheap-model", "--workspace", str(tmp_path)]

    # The starting command in a process group of its own, standing in for the Claude session.
    started = subprocess.Popen(command, cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    out, err = started.communicate(timeout=60)

    assert started.returncode == 0, err
    log = Path(out.strip().splitlines()[-1].removeprefix("log: "))
    try:
        os.killpg(started.pid, signal.SIGKILL)  # what closing the session does to everything still in its group
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and "harness exited 3" not in (log.read_text() if log.is_file() else ""):
        time.sleep(0.2)
    assert "harness exited 3" in log.read_text()
    assert json.dumps("never-used") not in log.read_text()
