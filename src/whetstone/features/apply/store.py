"""A run's files as apply reads them, in `prompts/<name>/runs/run-<id>/`."""

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
    runs = sorted(folder for folder in (prompt_dir / "runs").glob("run-*") if (folder / "candidate.txt").is_file())
    if not runs:
        raise RunError(f"no run of {prompt_dir.name} has a candidate; run whetstone run {prompt_dir.name} first")
    return runs[-1]
