"""The harness subprocess: one case as JSON on stdin, the production request as JSON on stdout."""

import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Any


class HarnessError(Exception):
    pass


def build_request(command: str, cwd: Path, case_json: str, timeout: float = 120) -> Any:
    # shell=True: the command comes from the workspace's own prompt.toml, written by its owner.
    # Its own session, so a timeout kills the whole group and not only the shell (a grandchild would hold the pipes open).
    with subprocess.Popen(
        command, shell=True, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True
    ) as process:
        try:
            stdout, stderr = process.communicate(case_json, timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise HarnessError(f"harness took longer than {timeout:g}s") from None
    if process.returncode != 0:
        raise HarnessError(f"harness exited {process.returncode}: {stderr.strip()}")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        raise HarnessError("harness printed invalid JSON") from None
