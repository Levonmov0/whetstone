"""Applying a run's candidate to the source: on a branch of its own, in a worktree of its own."""

import json
from pathlib import Path

from whetstone.entry.suite import Stop
from whetstone.features.apply.core import replace_once, run_line, warnings
from whetstone.features.apply.store import RunError, candidate_run, run_record
from whetstone.features.baseline.core import swipe_tally
from whetstone.features.cases.load import load_cases
from whetstone.features.grading.store import load_labels
from whetstone.features.workspace.load import PromptSettings
from whetstone.platform.git import add_worktree, branch_exists, commit_all, has_file, head, remove_worktree, show, toplevel
from whetstone.platform.harness import HarnessError, build_request


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
    start, source_rel = head(repo), source.relative_to(repo)
    applied = replace_once(show(repo, start, source_rel), record.original, candidate)
    if applied is None:
        raise Stop(f"{source_rel} no longer holds the text this run optimized exactly once; rerun the run on today's code")
    prompt_rel = prompt.dir.resolve().relative_to(repo)
    if not has_file(repo, start, prompt_rel / "editable.txt"):
        raise Stop(f"{prompt_rel / 'editable.txt'} isn't committed; commit the workspace first, as the branch starts from your last commit")
    add_worktree(repo, worktree, branch, start)
    (worktree / source_rel).write_text(applied)
    (worktree / prompt_rel / "editable.txt").write_text(candidate)
    verify_branch(prompt, repo, worktree)
    commit_all(worktree, f"whetstone: apply {folder.name} to {prompt.dir.name}\n\nReport: {prompt_rel / 'runs' / folder.name / 'report.md'}")
    remove_worktree(repo, worktree)
    print(f"committed the candidate on branch {branch}; nothing was pushed")
    return 0


def verify_branch(prompt: PromptSettings, repo: Path, worktree: Path) -> None:
    """Builds every case's request with the harness from the branch, so it is the branch's code that is checked."""
    workspace = worktree / prompt.workspace.resolve().relative_to(repo)
    for case_id, case_json in load_cases(prompt.dir):
        try:
            build_request(prompt.harness, workspace, case_json)
        except HarnessError as e:
            raise Stop(f"case {case_id}: on the branch, {e}\nSet up the worktree at {worktree} (install its dependencies), then run whetstone apply {prompt.dir.name} --verify") from None
