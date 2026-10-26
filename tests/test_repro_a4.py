import json
import threading
from pathlib import Path
from typing import Any

from whetstone.features.grading.store import load_deck, save_deck


def test_a_reader_never_sees_a_half_written_deck(tmp_path: Path) -> None:
    # `whetstone check` rewrites the deck while the serve process reads it on every request.
    cards: list[dict[str, Any]] = [{"case_id": f"c{i}", "input": {"text": "x" * 2000}, "output": "y" * 2000, "caught_by": []} for i in range(200)]
    save_deck(tmp_path, "daily", cards)
    done = threading.Event()
    errors: list[Exception] = []

    def read() -> None:
        while not done.is_set():
            try:
                load_deck(tmp_path, "daily")
            except json.JSONDecodeError as e:
                errors.append(e)
                return

    reader = threading.Thread(target=read)
    reader.start()
    try:
        for _ in range(200):
            save_deck(tmp_path, "daily", cards)
            if errors:
                break
    finally:
        done.set()
        reader.join()

    assert not errors, f"a reader saw a truncated deck: {errors[0]}"
