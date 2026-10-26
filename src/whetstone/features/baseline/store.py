"""A baseline run's files: which model wrote each card, and the report, in `prompts/<name>/runs/baseline-<deck-id>/`."""

import json
from pathlib import Path


def save_run(prompt_dir: Path, deck_id: str, card_models: dict[str, str], report: str) -> Path:
    """`card_models` maps each card id to its model; it holds no outputs, so the folder can be committed."""
    folder = prompt_dir / "runs" / f"baseline-{deck_id}"
    folder.mkdir(parents=True)
    (folder / "cards.json").write_text(json.dumps(card_models, indent=2))
    (folder / "report.md").write_text(report)
    return folder
