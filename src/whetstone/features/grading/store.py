"""Grading's files: the deck of cards to swipe, kept in the workspace's private `.whetstone/` folder."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from whetstone.platform import jsonl


def private_dir(workspace: Path) -> Path:
    """Whetstone's own runtime folder, with its own ignore file so it never reaches git."""
    folder = workspace / ".whetstone"
    folder.mkdir(exist_ok=True)
    (folder / ".gitignore").write_text("*\n")
    return folder


def new_deck_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def save_deck(workspace: Path, prompt: str, cards: list[dict[str, Any]], deck_id: str | None = None) -> str:
    """Replace the prompt's deck, and give its id. Each card is case_id, input, output and caught_by, plus a tag when one
    case has several cards; card ids, `<deck-id>:<case-id>[:<tag>]`, are added here."""
    deck_id = deck_id or new_deck_id()
    decks = private_dir(workspace) / "decks"
    decks.mkdir(exist_ok=True)
    deck = {"id": deck_id, "cards": [{"card_id": _card_id(deck_id, c), **{k: v for k, v in c.items() if k != "tag"}} for c in cards]}
    # Written aside, then swapped in: the server reads the deck on every request, and must never see half of one.
    partial = decks / f".{prompt}.json.partial"
    partial.write_text(json.dumps(deck, indent=2))
    partial.replace(decks / f"{prompt}.json")
    return deck_id


def _card_id(deck_id: str, card: dict[str, Any]) -> str:
    return f"{deck_id}:{card['case_id']}" + (f":{card['tag']}" if "tag" in card else "")


def load_deck(workspace: Path, prompt: str) -> dict[str, Any] | None:
    deck = workspace / ".whetstone" / "decks" / f"{prompt}.json"
    return json.loads(deck.read_text()) if deck.is_file() else None


def add_label(prompt_dir: Path, label: dict[str, Any]) -> None:
    jsonl.append(jsonl.file_for(prompt_dir, label["case_id"], "labels.jsonl"), label)


def load_labels(prompt_dir: Path) -> list[dict[str, Any]]:
    """Every label, the prompt's own and each real-data source's."""
    return [label for f in jsonl.files(prompt_dir, "labels.jsonl") for label in jsonl.read(f)]
