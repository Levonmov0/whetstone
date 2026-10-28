"""A run's files as apply reads them, in `prompts/<name>/runs/run-<id>/`."""

from pathlib import Path


def candidate_run(prompt_dir: Path, run_id: str | None) -> Path:
    """The run named `run_id`, or else the latest run with a candidate; run ids are timestamps, so names sort by time."""
    if run_id is not None:
        return prompt_dir / "runs" / f"run-{run_id}"
    return sorted(folder for folder in (prompt_dir / "runs").glob("run-*") if (folder / "candidate.txt").is_file())[-1]
