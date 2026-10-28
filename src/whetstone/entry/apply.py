"""Applying a run's candidate to the source: on a branch of its own, in a worktree of its own."""

from whetstone.entry.suite import Stop
from whetstone.features.apply.store import RunError, candidate_run, run_record
from whetstone.features.workspace.load import PromptSettings


def apply_candidate(prompt: PromptSettings, run_id: str | None) -> int:
    try:
        folder = candidate_run(prompt.dir, run_id)
        run_record(folder)
    except RunError as e:
        raise Stop(str(e)) from None
    print(f"{folder.name},")
    return 1
