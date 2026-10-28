"""Applying a run's candidate to the source: on a branch of its own, in a worktree of its own."""

import json
from dataclasses import dataclass
from pathlib import Path

from whetstone.entry.suite import Stop, source_file
from whetstone.features.apply.core import replace_once, run_line, warnings
from whetstone.features.apply.store import RunError, candidate_run, run_record, write_export
from whetstone.features.baseline.core import swipe_tally
from whetstone.features.cases.load import CaseError, load_cases
from whetstone.features.grading.store import load_labels
from whetstone.features.workspace.core import expand, rendered_texts
from whetstone.features.workspace.load import PromptSettings
from whetstone.platform.git import GitError, add_worktree, branch_exists, changed_files, commit, delete_branch, diff, has_file, head, remove_worktree, show, toplevel
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
    candidate = (folder / "candidate.txt").read_bytes().decode()
    source = source_file(prompt)
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
    verify_command = f"whetstone apply {prompt.dir.name} --run {run_id}" + (f" --folder {out}" if out else "") + " --verify"
    start, source_rel = head(repo), source.relative_to(repo)
    staged = None if prompt.apply == "code-edit" else [source_rel, *([editable] if editable else [])]
    branched = Branch(repo, branch, worktree, editable, folder, out / f"{prompt.dir.name}-{run_id}" if out else None, verify_command, staged)
    if branched.export and branched.export.exists():
        raise Stop(f"{branched.export} already exists; move it or choose another folder")
    if verify:
        if not worktree.is_dir():
            raise Stop(f"no apply branch of {folder.name} is waiting at {worktree}; run whetstone apply {prompt.dir.name} first")
        return commit_verified(prompt, branched, candidate)
    if branch_exists(repo, branch):
        raise Stop(f"branch {branch} already exists; delete it or apply another run")
    if editable and not has_file(repo, start, editable):
        raise Stop(f"{editable} isn't committed; commit the workspace first, as the branch starts from your last commit")
    if prompt.apply == "code-edit":
        if not editable:
            raise Stop("a code edit needs the workspace in the repo, so its harness can build the request from the branch")
        add_worktree(repo, worktree, branch, start)
        print(f"made branch {branch} at {worktree}; edit the code there so the prompt it builds holds the new text")
        print(f"\nold text:\n{record.original}\n\nnew text:\n{candidate}\n")
        print(f"then run {verify_command}")
        return 0
    applied = replace_once(show(repo, start, source_rel).decode(), record.original, candidate)
    if applied is None:
        raise Stop(f"{source_rel} no longer holds the text this run optimized exactly once; rerun the run on today's code")
    add_worktree(repo, worktree, branch, start)
    (worktree / source_rel).write_text(applied, newline="")
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
    verify_command: str  # what finishes this apply once the worktree is set up or edited
    staged: list[Path] | None  # what the commit takes: the files an exact apply wrote, or None for every change


def commit_verified(prompt: PromptSettings, branch: Branch, candidate: str) -> int:
    """Commits the branch once the request its harness builds holds the candidate; a workspace outside the repo can't
    build from the branch, so its exact replacement is the proof."""
    if branch.editable:
        if missing := verify_branch(prompt, branch, candidate):
            case_id, times = missing
            if branch.staged is not None:
                # The text was replaced where it is written, so the harness builds the request from elsewhere: no edit
                # in this worktree would fix that, and the branch would only be in the way of the next apply.
                remove_worktree(branch.repo, branch.worktree)
                delete_branch(branch.repo, branch.name)
                source = branch.staged[0]
                raise Stop(f"candidate found {times} times in the request for case {case_id}, though it replaced the text in {source}: its harness doesn't build the request from {source}; set apply = \"code-edit\" in prompt.toml and apply again")
            print(f"candidate found {times} times in the request for case {case_id}; edit the code in {branch.worktree} until it is there once")
            return 1
        (branch.worktree / branch.editable).write_text(candidate, newline="")
    report = branch.editable.parent / "runs" / branch.run.name / "report.md" if branch.editable else branch.run / "report.md"
    # A code edit's commit takes every change, its tests' too, and says which; an exact one takes only what it wrote.
    files = commit(branch.worktree, f"whetstone: apply {branch.run.name} to {prompt.dir.name}\n\nReport: {report}", branch.staged)
    print(f"committed {', '.join(files)}")
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


def verify_branch(prompt: PromptSettings, branch: Branch, candidate: str) -> tuple[str, int] | None:
    """Builds every case's request with the harness from the branch, so it is the branch's code that is checked; the
    first case whose request doesn't hold the candidate exactly once, and how many times it does, or None."""
    workspace = branch.worktree / prompt.workspace.resolve().relative_to(branch.repo)
    expanded = expand(candidate, prompt.placeholders)
    try:
        cases = load_cases(prompt.dir)
    except CaseError as e:
        raise Stop(f"{e}\nThen run {branch.verify_command}") from None
    for case_id, case_json in cases:
        try:
            request = build_request(prompt.harness, workspace, case_json)
        except HarnessError as e:
            raise Stop(f"case {case_id}: on the branch, {e}\nSet up the worktree at {branch.worktree} (install its dependencies), then run {branch.verify_command}") from None
        times = sum(text.count(expanded) for text in rendered_texts(request))
        if times != 1:
            return case_id, times
    return None
