"""Applying a run's candidate to the source: on a branch of its own, in a worktree of its own."""

import json
from dataclasses import dataclass
from pathlib import Path

from whetstone.entry.suite import Stop
from whetstone.features.apply.core import replace_once, run_line, warnings
from whetstone.features.apply.store import RunError, candidate_run, run_record, write_export
from whetstone.features.baseline.core import swipe_tally
from whetstone.features.cases.load import load_cases
from whetstone.features.grading.store import load_labels
from whetstone.features.workspace.core import expand, rendered_texts
from whetstone.features.workspace.load import PromptSettings
from whetstone.platform.git import GitError, add_worktree, branch_exists, changed_files, commit_all, delete_branch, diff, has_file, head, remove_worktree, show, toplevel
from whetstone.platform.harness import HarnessError, build_request


def apply_candidate(prompt: PromptSettings, run_id: str | None, yes: bool, verify: bool, out: Path | None) -> int:
    try:
        return _apply(prompt, run_id, yes, verify, out)
    except GitError as e:  # a hook that refused the commit, a worktree folder in the way, another apply racing this one
        raise Stop(str(e)) from None


def _apply(prompt: PromptSettings, run_id: str | None, yes: bool, verify: bool, out: Path | None) -> int:
    try:
        folder = candidate_run(prompt.dir, run_id)
        record = run_record(folder)
    except RunError as e:
        raise Stop(str(e)) from None
    print(run_line(folder.name, record.model, prompt.model, record.cases, record.original_clean, record.candidate_clean))
    if not verify:
        tally = swipe_tally(load_labels(prompt.dir), folder.name.removeprefix("run-"), json.loads((folder / "cards.json").read_text()))
        found = warnings(tally, record.within_noise)
        print("".join(f"warning: {line}\n" for line in found), end="")
        if found and not yes:
            print("rerun with --yes to apply it anyway")
            return 1
    candidate = (folder / "candidate.txt").read_text()
    source = (prompt.workspace / str(prompt.source)).resolve()
    try:
        repo = toplevel(source.parent)
    except GitError:
        raise Stop(f"{prompt.source} isn't in a git repo; apply commits the candidate on a branch") from None
    run_id = folder.name.removeprefix("run-")
    branch = f"whetstone/{prompt.dir.name}-{run_id}"
    # Beside the repo, not in it: test runners and compilers at the repo's root would find a nested copy.
    worktree = repo.parent / f"{repo.name}.worktrees" / f"whetstone-{prompt.dir.name}-{run_id}"
    # A workspace in the repo moves with the branch: its editable.txt is updated there, and its harness builds from it.
    inside = prompt.dir.resolve().is_relative_to(repo)
    editable = prompt.dir.resolve().relative_to(repo) / "editable.txt" if inside else None
    branched = Branch(repo, branch, worktree, editable, folder, out / f"{prompt.dir.name}-{run_id}" if out else None)
    if branched.export and branched.export.exists():
        raise Stop(f"{branched.export} already exists; move it or choose another folder")
    if verify:
        if not worktree.is_dir():
            raise Stop(f"no apply branch of {folder.name} is waiting at {worktree}; run whetstone apply {prompt.dir.name} first")
        return commit_verified(prompt, branched, candidate)
    if branch_exists(repo, branch):
        raise Stop(f"branch {branch} already exists; delete it or apply another run")
    start, source_rel = head(repo), source.relative_to(repo)
    if editable and not has_file(repo, start, editable):
        raise Stop(f"{editable} isn't committed; commit the workspace first, as the branch starts from your last commit")
    if prompt.apply == "code-edit":
        if not editable:
            raise Stop("a code edit needs the workspace in the repo, so its harness can build the request from the branch")
        add_worktree(repo, worktree, branch, start)
        print(f"made branch {branch} at {worktree}; edit the code there so the prompt it builds holds the new text")
        print(f"\nold text:\n{record.original}\n\nnew text:\n{candidate}\n")
        print(f"then run whetstone apply {prompt.dir.name} --verify")
        return 0
    applied = replace_once(show(repo, start, source_rel), record.original, candidate)
    if applied is None:
        raise Stop(f"{source_rel} no longer holds the text this run optimized exactly once; rerun the run on today's code")
    add_worktree(repo, worktree, branch, start)
    (worktree / source_rel).write_text(applied)
    return commit_verified(prompt, branched, candidate)


@dataclass(frozen=True)
class Branch:
    """Where a candidate is applied: its branch, checked out in its own worktree."""

    repo: Path
    name: str
    worktree: Path
    editable: Path | None  # the prompt's editable.txt, relative to the repo; None when the workspace is outside it
    run: Path  # the run's folder
    export: Path | None  # the folder target: the change is written here, and the branch deleted


def commit_verified(prompt: PromptSettings, branch: Branch, candidate: str) -> int:
    """Commits the branch once the request its harness builds holds the candidate; a workspace outside the repo can't
    build from the branch, so its exact replacement is the proof."""
    if branch.editable:
        if problem := verify_branch(prompt, branch.repo, branch.worktree, candidate):
            print(problem)
            return 1
        (branch.worktree / branch.editable).write_text(candidate)
    report = branch.editable.parent / "runs" / branch.run.name / "report.md" if branch.editable else branch.run / "report.md"
    commit_all(branch.worktree, f"whetstone: apply {branch.run.name} to {prompt.dir.name}\n\nReport: {report}")
    remove_worktree(branch.repo, branch.worktree)
    if branch.export:
        base = f"{branch.name}~1"
        files = {path: show(branch.repo, branch.name, Path(path)) for path in changed_files(branch.repo, base, branch.name)}
        write_export(branch.export, diff(branch.repo, base, branch.name), files)
        delete_branch(branch.repo, branch.name)
        print(f"wrote the change to {branch.export}: change.patch applies with git apply")
    else:
        print(f"committed the candidate on branch {branch.name}; nothing was pushed")
    if not branch.editable:
        print("the workspace is outside the repo, so its editable.txt still holds the original: after merging, rerun /whetstone:init's editable step")
    return 0


def verify_branch(prompt: PromptSettings, repo: Path, worktree: Path, candidate: str) -> str | None:
    """Builds every case's request with the harness from the branch, so it is the branch's code that is checked; why
    the candidate isn't in one of them exactly once, or None."""
    workspace = worktree / prompt.workspace.resolve().relative_to(repo)
    expanded = expand(candidate, prompt.placeholders)
    for case_id, case_json in load_cases(prompt.dir):
        try:
            request = build_request(prompt.harness, workspace, case_json)
        except HarnessError as e:
            raise Stop(f"case {case_id}: on the branch, {e}\nSet up the worktree at {worktree} (install its dependencies), then run whetstone apply {prompt.dir.name} --verify") from None
        times = sum(text.count(expanded) for text in rendered_texts(request))
        if times != 1:
            return f"candidate found {times} times in the request for case {case_id}; edit the code in {worktree} until it is there once"
    return None
