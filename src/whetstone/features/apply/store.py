"""A run's files as apply reads them, in `prompts/<name>/runs/run-<id>/`."""

import json
from dataclasses import dataclass
from pathlib import Path


class RunError(Exception):
    pass


def candidate_run(prompt_dir: Path, run_id: str | None) -> Path:
    """The run named `run_id`, or else the latest run with a candidate; run ids are timestamps, so names sort by time."""
    if run_id is not None:
        folder = prompt_dir / "runs" / f"run-{run_id}"
        if not (folder / "candidate.txt").is_file():
            raise RunError(f"{folder.name} has no candidate")
        return folder
    # cards.json is a winner's last file, so a run still writing its files is passed over.
    runs = sorted(folder for folder in (prompt_dir / "runs").glob("run-*") if (folder / "candidate.txt").is_file() and (folder / "cards.json").is_file())
    if not runs:
        raise RunError(f"no run of {prompt_dir.name} has a candidate; run whetstone run {prompt_dir.name} first")
    return runs[-1]


@dataclass(frozen=True)
class RunRecord:
    """What a run with a candidate recorded in run.json."""

    model: str
    original: str  # the editable part the run optimized, in its source form
    cases: int  # held-back cases
    original_clean: int  # held-back cases the original passed every check on
    candidate_clean: int
    within_noise: bool
    unmeasured_judges: list[str]  # judges never measured on bad swipes, which the candidate was optimized against untested


def run_record(folder: Path) -> RunRecord:
    record = json.loads((folder / "run.json").read_text())
    if "held_back" not in record:
        raise RunError(f"{folder.name} was made before apply existed and has no recorded result; run it again")
    held = record["held_back"]
    # A run made before unmeasured judges existed had none: it couldn't start against a judge short of bad swipes.
    return RunRecord(record["model"], record["original"], held["cases"], held["original"], held["candidate"], record["within_noise"], record.get("unmeasured_judges", []))


def write_export(folder: Path, patch: bytes, files: dict[str, bytes]) -> None:
    """A candidate applied to a folder: `change.patch`, and each changed file at its path in the repo."""
    folder.mkdir(parents=True)
    (folder / "change.patch").write_bytes(patch)
    for path, content in files.items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_bytes(content)
