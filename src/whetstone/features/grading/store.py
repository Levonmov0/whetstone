"""Grading's files: the deck of cards to swipe, kept in the workspace's private `.whetstone/` folder."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def private_dir(workspace: Path) -> Path:
    """Whetstone's own runtime folder, with its own ignore file so it never reaches git."""
    folder = workspace / ".whetstone"
    folder.mkdir(exist_ok=True)
    (folder / ".gitignore").write_text("*\n")
    return folder


def save_deck(workspace: Path, prompt: str, cards: list[dict[str, Any]]) -> None:
    """Replace the prompt's deck. Each card is case_id, input, output and caught_by; card ids are added here."""
    deck_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    decks = private_dir(workspace) / "decks"
    decks.mkdir(exist_ok=True)
    deck = {"id": deck_id, "cards": [{"card_id": f"{deck_id}:{c['case_id']}", **c} for c in cards]}
    (decks / f"{prompt}.json").write_text(json.dumps(deck, indent=2))


def load_deck(workspace: Path, prompt: str) -> dict[str, Any] | None:
    deck = workspace / ".whetstone" / "decks" / f"{prompt}.json"
    return json.loads(deck.read_text()) if deck.is_file() else None


def add_label(prompt_dir: Path, label: dict[str, Any]) -> None:
    with _labels_file(prompt_dir, label["case_id"]).open("a") as f:
        f.write(json.dumps(label) + "\n")


def _labels_file(prompt_dir: Path, case_id: str) -> Path:
    # A real-data case's labels quote its input, so they live in its gitignored source folder.
    if case_id.startswith("private/"):
        return prompt_dir / "cases" / Path(case_id).parent / "labels.jsonl"
    return prompt_dir / "labels.jsonl"


def load_labels(prompt_dir: Path) -> list[dict[str, Any]]:
    """Every label, the prompt's own and each real-data source's."""
    files = [prompt_dir / "labels.jsonl", *(prompt_dir / "cases" / "private").glob("*/labels.jsonl")]
    return [json.loads(line) for f in files if f.is_file() for line in f.read_text().splitlines()]
