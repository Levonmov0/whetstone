"""Applying a run's candidate to the source: on a branch of its own, in a worktree of its own."""

import json

from whetstone.entry.suite import Stop
from whetstone.features.apply.core import run_line, warnings
from whetstone.features.apply.store import RunError, candidate_run, run_record
from whetstone.features.baseline.core import swipe_tally
from whetstone.features.grading.store import load_labels
from whetstone.features.workspace.load import PromptSettings


def apply_candidate(prompt: PromptSettings, run_id: str | None, yes: bool) -> int:
    try:
        folder = candidate_run(prompt.dir, run_id)
        record = run_record(folder)
    except RunError as e:
        raise Stop(str(e)) from None
    print(run_line(folder.name, record.model, prompt.model, record.cases, record.original_clean, record.candidate_clean))
    tally = swipe_tally(load_labels(prompt.dir), folder.name.removeprefix("run-"), json.loads((folder / "cards.json").read_text()))
    found = warnings(tally)
    print("".join(f"warning: {line}\n" for line in found), end="")
    if found and not yes:
        print("rerun with --yes to apply it anyway")
        return 1
    return 0
