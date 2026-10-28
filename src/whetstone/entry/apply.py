"""Applying a run's candidate to the source: on a branch of its own, in a worktree of its own."""

from whetstone.features.apply.store import candidate_run
from whetstone.features.workspace.load import PromptSettings


def apply_candidate(prompt: PromptSettings, run_id: str | None) -> int:
    folder = candidate_run(prompt.dir, run_id)
    print(f"{folder.name},")
    return 1
