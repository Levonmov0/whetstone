"""A baseline run's files: which model wrote each card, and the report, in `prompts/<name>/runs/baseline-<deck-id>/`."""

import json
from pathlib import Path


def save_run(prompt_dir: Path, deck_id: str, card_models: dict[str, str], report: str) -> None:
    """`card_models` maps each card's tag to its model. Tags are random and name no case, and the report holds only
    counts, so the folder can be committed even when some cases are real data."""
    folder = prompt_dir / "runs" / f"baseline-{deck_id}"
    folder.mkdir(parents=True)
    (folder / "cards.json").write_text(json.dumps(card_models, indent=2))
    (folder / "report.md").write_text(report)


def latest_run(prompt_dir: Path) -> Path | None:
    """The newest baseline run's folder; deck ids are timestamps, so the names sort by time."""
    runs = sorted((prompt_dir / "runs").glob("baseline-*"))
    return runs[-1] if runs else None


def card_models(folder: Path) -> dict[str, str]:
    return json.loads((folder / "cards.json").read_text())
