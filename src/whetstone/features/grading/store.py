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
