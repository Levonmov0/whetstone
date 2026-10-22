"""The harness subprocess: one case as JSON on stdin, the production request as JSON on stdout."""

import json
import subprocess
from pathlib import Path
from typing import Any


class HarnessError(Exception):
    pass


def build_request(command: str, cwd: Path, case_json: str) -> Any:
    # shell=True: the command comes from the workspace's own prompt.toml, written by its owner.
    done = subprocess.run(command, shell=True, cwd=cwd, input=case_json, capture_output=True, text=True)
    if done.returncode != 0:
        raise HarnessError(f"harness exited {done.returncode}: {done.stderr.strip()}")
    try:
        return json.loads(done.stdout)
    except json.JSONDecodeError:
        raise HarnessError("harness printed invalid JSON") from None
