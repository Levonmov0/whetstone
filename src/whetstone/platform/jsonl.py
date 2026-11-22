"""Append-only JSON-lines files that several processes write and read: the server, `map` and `notes --follow`."""

import fcntl
import json
from pathlib import Path
from typing import Any


def append(path: Path, record: dict[str, Any]) -> None:
    with path.open("a") as f:
        # A long line goes out in several writes, so each append holds the file until its line is whole.
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(record) + "\n")


def read(path: Path) -> list[dict[str, Any]]:
    """Every record, or none for a file not written yet. A read waits for a line being appended to be whole."""
    if not path.is_file():
        return []
    with path.open() as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        return [json.loads(line) for line in f.read().splitlines()]
