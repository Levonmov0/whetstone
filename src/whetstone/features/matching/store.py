"""Matching's file: `matches.jsonl`, the append-only log of Claude's matches, beside the labels it matches."""

import json
from pathlib import Path
from typing import Any


def load_events(prompt_dir: Path) -> list[dict[str, Any]]:
    """Every match event."""
    file = prompt_dir / "matches.jsonl"
    return [json.loads(line) for line in file.read_text().splitlines()] if file.is_file() else []


def add_event(prompt_dir: Path, event: dict[str, Any]) -> None:
    with (prompt_dir / "matches.jsonl").open("a") as f:
        f.write(json.dumps(event) + "\n")
