"""Grading's files: the deck of cards to swipe, kept in the workspace's private `.whetstone/` folder."""

import fcntl
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
    with _labels_file(prompt_dir, label["case_id"]).open("a") as f:
        # The server and `map` append from separate processes; a long line goes out in several writes, so each
        # append holds the file until its line is whole.
        fcntl.flock(f, fcntl.LOCK_EX)
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
