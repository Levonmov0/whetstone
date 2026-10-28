"""Applying a run's candidate to the source: on a branch of its own, in a worktree of its own."""

from whetstone.entry.suite import Stop
from whetstone.features.apply.core import run_line
from whetstone.features.apply.store import RunError, candidate_run, run_record
from whetstone.features.workspace.load import PromptSettings


def apply_candidate(prompt: PromptSettings, run_id: str | None) -> int:
    try:
        folder = candidate_run(prompt.dir, run_id)
        record = run_record(folder)
    except RunError as e:
        raise Stop(str(e)) from None
    print(run_line(folder.name, record.model, prompt.model, record.cases, record.original_clean, record.candidate_clean))
    return 1
