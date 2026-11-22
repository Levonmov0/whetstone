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


def files(prompt_dir: Path, name: str) -> list[Path]:
    """A prompt's own file of this name and each real-data source's."""
    return [prompt_dir / name, *(prompt_dir / "cases" / "private").glob(f"*/{name}")]


def file_for(prompt_dir: Path, case_id: str, name: str) -> Path:
    # A real-data case's records quote its input or the grader's reading of it, so they live in its gitignored source folder.
    return prompt_dir / "cases" / Path(case_id).parent / name if case_id.startswith("private/") else prompt_dir / name
