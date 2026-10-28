"""Applying a run's candidate to the source: on a branch of its own, in a worktree of its own."""

import json

from whetstone.entry.suite import Stop
from whetstone.features.apply.core import run_line, warnings
from whetstone.features.apply.store import RunError, candidate_run, run_record
from whetstone.features.baseline.core import swipe_tally
from whetstone.features.grading.store import load_labels
from whetstone.features.workspace.load import PromptSettings
from whetstone.platform.git import add_worktree, branch_exists, commit_all, head, remove_worktree, toplevel


def apply_candidate(prompt: PromptSettings, run_id: str | None, yes: bool) -> int:
    try:
        folder = candidate_run(prompt.dir, run_id)
        record = run_record(folder)
    except RunError as e:
        raise Stop(str(e)) from None
    print(run_line(folder.name, record.model, prompt.model, record.cases, record.original_clean, record.candidate_clean))
    tally = swipe_tally(load_labels(prompt.dir), folder.name.removeprefix("run-"), json.loads((folder / "cards.json").read_text()))
    found = warnings(tally, record.within_noise)
    print("".join(f"warning: {line}\n" for line in found), end="")
    if found and not yes:
        print("rerun with --yes to apply it anyway")
        return 1
    candidate = (folder / "candidate.txt").read_text()
    source = (prompt.workspace / str(prompt.source)).resolve()
    repo = toplevel(source.parent)
    run_id = folder.name.removeprefix("run-")
    branch = f"whetstone/{prompt.dir.name}-{run_id}"
    if branch_exists(repo, branch):
        raise Stop(f"branch {branch} already exists; delete it or apply another run")
    # Beside the repo, not in it: test runners and compilers at the repo's root would find a nested copy.
    worktree = repo.parent / f"{repo.name}.worktrees" / f"whetstone-{prompt.dir.name}-{run_id}"
    add_worktree(repo, worktree, branch, head(repo))
    changed = worktree / source.relative_to(repo)
    changed.write_text(changed.read_text().replace(record.original, candidate))
    prompt_rel = prompt.dir.resolve().relative_to(repo)
    (worktree / prompt_rel / "editable.txt").write_text(candidate)
    commit_all(worktree, f"whetstone: apply {folder.name} to {prompt.dir.name}\n\nReport: {prompt_rel / 'runs' / folder.name / 'report.md'}")
    remove_worktree(repo, worktree)
    print(f"committed the candidate on branch {branch}; nothing was pushed")
    return 0
