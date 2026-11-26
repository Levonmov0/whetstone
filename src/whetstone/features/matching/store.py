"""Matching's file: `matches.jsonl`, the append-only log of Claude's matches, beside the labels it matches."""

from pathlib import Path
from typing import Any

from whetstone.features.matching.core import Snapshot
from whetstone.platform import jsonl


def load_events(prompt_dir: Path) -> list[dict[str, Any]]:
    """Every match event, the prompt's own and each real-data source's."""
    return [event for f in jsonl.files(prompt_dir, "matches.jsonl") for event in jsonl.read(f)]


def snapshot(prompt_dir: Path) -> Snapshot:
    """The match events and the labels together, the only way to read both, and the only reader of Claude's matched
    lines: split here from graders' swipes, once. Events first: every event is written after the lines it names, so the
    labels read next hold each one's swipe. A line newer than the events is read too, and a line no event owns yet
    never counts."""
    events = load_events(prompt_dir)
    labels = [label for f in jsonl.files(prompt_dir, "labels.jsonl") for label in jsonl.read(f)]
    return Snapshot(events, [label for label in labels if "matched_by" not in label], [label for label in labels if "matched_by" in label])


def add_event(prompt_dir: Path, case_id: str, event: dict[str, Any]) -> None:
    jsonl.append(jsonl.file_for(prompt_dir, case_id, "matches.jsonl"), event)
