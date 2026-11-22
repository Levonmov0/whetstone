"""Matching's file: `matches.jsonl`, the append-only log of Claude's matches, beside the labels it matches."""

from pathlib import Path
from typing import Any

from whetstone.platform import jsonl


def load_events(prompt_dir: Path) -> list[dict[str, Any]]:
    """Every match event, the prompt's own and each real-data source's."""
    files = [prompt_dir / "matches.jsonl", *(prompt_dir / "cases" / "private").glob("*/matches.jsonl")]
    return [event for f in files for event in jsonl.read(f)]


def add_event(prompt_dir: Path, case_id: str, event: dict[str, Any]) -> None:
    # A real-data case's match quotes the grader's reading of it, so it lives in its gitignored source folder, as the
    # case's labels do.
    folder = prompt_dir / "cases" / Path(case_id).parent if case_id.startswith("private/") else prompt_dir
    jsonl.append(folder / "matches.jsonl", event)
