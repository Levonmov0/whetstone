"""Matching's file: `matches.jsonl`, the append-only log of Claude's matches, beside the labels it matches."""

from pathlib import Path
from typing import Any

from whetstone.platform import jsonl


def load_events(prompt_dir: Path) -> list[dict[str, Any]]:
    """Every match event, the prompt's own and each real-data source's."""
    return [event for f in jsonl.files(prompt_dir, "matches.jsonl") for event in jsonl.read(f)]


def add_event(prompt_dir: Path, case_id: str, event: dict[str, Any]) -> None:
    jsonl.append(jsonl.file_for(prompt_dir, case_id, "matches.jsonl"), event)
