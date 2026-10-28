import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeModel, unused_model
from whetstone.entry.cli import run

OLDER, LATER, NEWEST = "20261027T080000000000Z", "20261028T080000000000Z", "20261028T090000000000Z"

# Builds the request from the repo's own source file, as a real harness calls the real prompt builder: the system prompt
# is the text between the backticks in src/prompt.txt, with ${VOICE} built as "Speak plainly.".
HARNESS = (
    "import json, sys\n"
    "case = json.load(sys.stdin)\n"
    "source = open('../src/prompt.txt').read()\n"
    "system = source.split('`')[1].replace('${VOICE}', 'Speak plainly.')\n"
    'print(json.dumps({"model": "prod-model", "max_tokens": 50, "system": system, "messages": [{"role": "user", "content": case["text"]}]}))\n'
)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


pytestmark = pytest.mark.usefixtures("plain_git")


def make_repo(root: Path, editable: str = "Be brief.", source: str = "PROMPT = `Be brief.`\n") -> Path:
    """A repo at root/repo with its workspace in whetstone/, committed on main; returns the prompt folder."""
    repo = root / "repo"
    prompt = repo / "whetstone" / "prompts" / "daily"
    (prompt / "cases").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "src" / "prompt.txt").write_text(source)
    (repo / "whetstone" / "whetstone.toml").write_text("")
    (prompt / "harness.py").write_text(HARNESS)
    settings = {"harness": f"{sys.executable} prompts/daily/harness.py", "provider": "anthropic", "model": "prod-model", "source": "../src/prompt.txt"}
    (prompt / "prompt.toml").write_text("".join(f"{k} = {json.dumps(v)}\n" for k, v in settings.items()))
    (prompt / "editable.txt").write_text(editable)
    for i in range(3):
        (prompt / "cases" / f"case-{i}.json").write_text(json.dumps({"text": f"Line {i}."}))
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "start")
    return prompt


def write_run(
    prompt: Path,
    run_id: str,
    candidate: str | None = "Be brief. Keep it short.",
    model: str = "prod-model",
    held: tuple[int, int, int] = (3, 1, 2),
    within_noise: bool = False,
    original: str = "Be brief.",
) -> Path:
    """A finished run's folder; with a candidate, its held-back result is `held`: cases, original and candidate clean."""
    folder = prompt / "runs" / f"run-{run_id}"
    folder.mkdir(parents=True)
    (folder / "report.md").write_text("# Run: daily\n")
    record: dict[str, Any] = {"model": model}
    if candidate is not None:
        (folder / "candidate.txt").write_text(candidate)
        (folder / "cards.json").write_text(json.dumps({"o1": "original", "c1": "candidate"}))
        record |= {"original": original, "held_back": {"cases": held[0], "original": held[1], "candidate": held[2]}, "within_noise": within_noise}
    (folder / "run.json").write_text(json.dumps(record))
    return folder


def apply(prompt: Path, *extra: str) -> int:
    return run(["apply", "daily", "--workspace", str(prompt.parent.parent), *extra], make_model=unused_model)


def test_apply_picks_the_latest_run_with_a_candidate_unless_told(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_repo(tmp_path)
    write_run(prompt, OLDER)
    write_run(prompt, LATER)
    write_run(prompt, NEWEST, candidate=None)

    apply(prompt)
    assert capsys.readouterr().out.startswith(f"run-{LATER},")
    apply(prompt, "--run", OLDER)
    assert capsys.readouterr().out.startswith(f"run-{OLDER},")


@pytest.mark.parametrize(("extra", "message"), [((), "no run of daily has a candidate"), (("--run", OLDER), f"run-{OLDER} has no candidate")])
def test_apply_needs_a_run_with_a_candidate(extra: tuple[str, ...], message: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_repo(tmp_path)
    write_run(prompt, NEWEST, candidate=None)

    assert apply(prompt, *extra) == 2
    assert message in capsys.readouterr().err


def test_a_run_made_before_apply_must_be_rerun(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_repo(tmp_path)
    folder = write_run(prompt, LATER)
    (folder / "run.json").write_text(json.dumps({"model": "prod-model"}))

    assert apply(prompt) == 2
    assert f"run-{LATER} was made before apply existed and has no recorded result; run it again" in capsys.readouterr().err


@pytest.mark.parametrize(("model", "named"), [("prod-model", "production model"), ("cheap-model", "cheap model cheap-model")])
def test_apply_names_the_run_first(model: str, named: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_repo(tmp_path)
    write_run(prompt, LATER, model=model)

    apply(prompt)

    assert capsys.readouterr().out.splitlines()[0] == f"run-{LATER}, {named}, 2/3 held-back passing vs 1/3 original"


def swipe(prompt: Path, run_id: str, tag: str, verdict: str, grader: str = "Levon") -> None:
    label: dict[str, Any] = {"card_id": f"{run_id}:case-0:{tag}", "case_id": "case-0", "grader": grader, "verdict": verdict, "reasons": [], "at": "2026-10-28T10:00:00+00:00"}
    with (prompt / "labels.jsonl").open("a") as labels:
        labels.write(json.dumps(label) + "\n")


def apply_branches(prompt: Path) -> str:
    return git(prompt, "branch", "--list", "whetstone/*")


def test_a_candidate_never_swiped_blind_is_warned_about(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_repo(tmp_path)
    write_run(prompt, LATER)

    assert apply(prompt) == 1
    assert "no blind swipe yet" in capsys.readouterr().out
    assert apply_branches(prompt) == ""
    assert apply(prompt, "--yes") == 0
    assert "no blind swipe yet" in capsys.readouterr().out


def test_a_gain_within_noise_is_warned_about(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_repo(tmp_path)
    write_run(prompt, LATER, within_noise=True)
    swipe(prompt, LATER, "c1", "good")

    assert apply(prompt) == 1
    assert "within noise" in capsys.readouterr().out


def test_a_blind_swipe_that_preferred_the_original_is_warned_about(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_repo(tmp_path)
    write_run(prompt, LATER)
    swipe(prompt, LATER, "o1", "good")
    swipe(prompt, LATER, "o1", "good", grader="Hampus")
    swipe(prompt, LATER, "c1", "good")

    assert apply(prompt) == 1
    assert "the blind swipe preferred the original" in capsys.readouterr().out


def swiped_run(prompt: Path, **run: Any) -> Path:
    """A run whose candidate won the blind swipe, so apply has nothing to warn about."""
    folder = write_run(prompt, LATER, **run)
    swipe(prompt, LATER, "c1", "good")
    return folder


BRANCH = f"whetstone/daily-{LATER}"


def test_an_exact_apply_commits_the_candidate_on_its_own_branch(tmp_path: Path) -> None:
    prompt = make_repo(tmp_path)
    repo = tmp_path / "repo"
    swiped_run(prompt)
    start = git(repo, "rev-parse", "HEAD")

    assert apply(prompt) == 0

    assert git(repo, "rev-parse", f"{BRANCH}~1") == start
    assert git(repo, "show", f"{BRANCH}:src/prompt.txt") == "PROMPT = `Be brief. Keep it short.`"
    assert git(repo, "show", f"{BRANCH}:whetstone/prompts/daily/editable.txt") == "Be brief. Keep it short."
    assert f"whetstone/prompts/daily/runs/run-{LATER}/report.md" in git(repo, "log", "-1", "--format=%B", BRANCH)
    checkout = tmp_path / "branch-checkout"
    git(repo, "worktree", "add", "-q", str(checkout), BRANCH)
    model = FakeModel(lambda _request: "ok")
    assert run(["check", "daily", "--workspace", str(checkout / "whetstone")], make_model=lambda _settings: model) == 0
    assert all(request["system"] == "Be brief. Keep it short." for request in model.requests)


def test_apply_leaves_the_users_checkout_alone_and_never_pushes(tmp_path: Path) -> None:
    prompt = make_repo(tmp_path)
    repo = tmp_path / "repo"
    git(tmp_path, "init", "-q", "--bare", "remote.git")
    git(repo, "remote", "add", "origin", str(tmp_path / "remote.git"))
    git(repo, "push", "-q", "origin", "main")
    git(repo, "switch", "-q", "-c", "my-work")
    (repo / "src" / "prompt.txt").write_text("PROMPT = `Be brief.`\n// half-done edit\n")
    (repo / "notes.txt").write_text("untracked")
    swiped_run(prompt)
    before = (git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain"), (repo / "src" / "prompt.txt").read_text())

    assert apply(prompt) == 0

    assert git(repo, "branch", "--show-current") == "my-work"
    assert (git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain"), (repo / "src" / "prompt.txt").read_text()) == before
    assert len(git(repo, "worktree", "list").splitlines()) == 1
    assert git(tmp_path / "remote.git", "branch", "--list", "whetstone/*") == ""


def test_a_placeholder_prompt_is_applied_in_its_source_form(tmp_path: Path) -> None:
    prompt = make_repo(tmp_path, editable="Be brief. ${VOICE}", source="PROMPT = `Be brief. ${VOICE}`\n")
    with (prompt / "prompt.toml").open("a") as toml:
        toml.write('[placeholders]\n"${VOICE}" = "Speak plainly."\n')
    git(tmp_path / "repo", "commit", "-qam", "placeholders")
    swiped_run(prompt, candidate="Be brief. ${VOICE} Keep it short.", original="Be brief. ${VOICE}")

    assert apply(prompt) == 0

    assert git(tmp_path / "repo", "show", f"{BRANCH}:src/prompt.txt") == "PROMPT = `Be brief. ${VOICE} Keep it short.`"


def test_an_existing_branch_name_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_repo(tmp_path)
    repo = tmp_path / "repo"
    git(repo, "branch", BRANCH)
    swiped_run(prompt)

    assert apply(prompt) == 2
    assert f"branch {BRANCH} already exists" in capsys.readouterr().err
    assert git(repo, "rev-parse", BRANCH) == git(repo, "rev-parse", "main")
    assert len(git(repo, "worktree", "list").splitlines()) == 1


@pytest.mark.parametrize("source", ["PROMPT = `Be short.`\n", "A = `Be brief.`\nB = `Be brief.`\n"])
def test_a_source_that_no_longer_holds_the_original_once_is_refused(source: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_repo(tmp_path, source=source)
    swiped_run(prompt)

    assert apply(prompt) == 2
    assert "src/prompt.txt no longer holds the text this run optimized exactly once" in capsys.readouterr().err
    assert apply_branches(prompt) == ""
    assert len(git(tmp_path / "repo", "worktree", "list").splitlines()) == 1


def test_the_applied_source_keeps_every_byte_around_the_candidate(tmp_path: Path) -> None:
    prompt = make_repo(tmp_path, source="PROMPT = `Be brief.`\n\n")
    swiped_run(prompt)

    assert apply(prompt) == 0

    shown = subprocess.run(["git", "show", f"{BRANCH}:src/prompt.txt"], cwd=tmp_path / "repo", capture_output=True, text=True, check=True).stdout
    assert shown == "PROMPT = `Be brief. Keep it short.`\n\n"


def test_a_harness_that_fails_on_the_branch_keeps_the_worktree_for_verify(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_repo(tmp_path)
    repo = tmp_path / "repo"
    # Like node_modules: the harness needs a file that is ignored, so a fresh worktree lacks it until set up.
    (prompt / "harness.py").write_text("open('deps.txt')\n" + HARNESS)
    (repo / ".gitignore").write_text("deps.txt\n")
    (repo / "whetstone" / "deps.txt").write_text("installed")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "harness needs deps")
    swiped_run(prompt)

    assert apply(prompt) == 2

    err = capsys.readouterr().err
    assert "harness exited 1" in err and "then run whetstone apply daily --verify" in err
    assert len(git(repo, "worktree", "list").splitlines()) == 2
    assert git(repo, "rev-parse", BRANCH) == git(repo, "rev-parse", "main")


def test_an_uncommitted_workspace_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_repo(tmp_path)
    repo = tmp_path / "repo"
    git(repo, "rm", "-q", "--cached", "whetstone/prompts/daily/editable.txt")
    git(repo, "commit", "-qm", "editable not committed yet")
    swiped_run(prompt)

    assert apply(prompt) == 2
    assert "commit the workspace first" in capsys.readouterr().err
    assert apply_branches(prompt) == ""
    assert len(git(repo, "worktree", "list").splitlines()) == 1


def test_a_source_outside_any_git_repo_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_repo(tmp_path)
    shutil.rmtree(tmp_path / "repo" / ".git")
    swiped_run(prompt)

    assert apply(prompt) == 2
    assert "src/prompt.txt isn't in a git repo" in capsys.readouterr().err


def outside_workspace(tmp_path: Path) -> Path:
    """The repo at tmp_path/repo, its workspace moved out to tmp_path/ws; returns the prompt folder."""
    make_repo(tmp_path)
    repo = tmp_path / "repo"
    shutil.move(repo / "whetstone", tmp_path / "ws")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "workspace lives outside")
    prompt = tmp_path / "ws" / "prompts" / "daily"
    for name in ("prompt.toml", "harness.py"):
        (prompt / name).write_text((prompt / name).read_text().replace("../src/prompt.txt", "../repo/src/prompt.txt"))
    return prompt


def test_a_workspace_outside_the_repo_is_left_alone(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = outside_workspace(tmp_path)
    repo = tmp_path / "repo"
    swiped_run(prompt)

    assert apply(prompt) == 0

    assert git(repo, "show", f"{BRANCH}:src/prompt.txt") == "PROMPT = `Be brief. Keep it short.`"
    assert git(repo, "diff", "--name-only", f"{BRANCH}~1", BRANCH) == "src/prompt.txt"
    assert (prompt / "editable.txt").read_text() == "Be brief."
    assert "after merging, rerun /whetstone:init's editable step" in capsys.readouterr().out


ASSEMBLED = "PROMPT = [`Be`, `brief.`].join(' ')\n"
WORKTREE = f"repo.worktrees/whetstone-daily-{LATER}"


def code_edit_repo(tmp_path: Path) -> Path:
    """A prompt whose editable part is assembled from parts in the source, so applying it means editing code."""
    prompt = make_repo(tmp_path, source=ASSEMBLED)
    with (prompt / "prompt.toml").open("a") as toml:
        toml.write('apply = "code-edit"\n')
    git(tmp_path / "repo", "commit", "-qam", "code edit")
    swiped_run(prompt)
    return prompt


def test_a_code_edit_apply_makes_the_branch_and_shows_the_edit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = code_edit_repo(tmp_path)
    repo = tmp_path / "repo"

    assert apply(prompt) == 0

    out = capsys.readouterr().out
    assert str((tmp_path / WORKTREE).resolve()) in out
    assert "Be brief.\n" in out and "Be brief. Keep it short.\n" in out
    assert git(repo, "rev-parse", BRANCH) == git(repo, "rev-parse", "main")
    assert git(tmp_path / WORKTREE, "status", "--porcelain") == ""


def test_verify_refuses_until_the_branch_builds_the_candidate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = code_edit_repo(tmp_path)
    repo = tmp_path / "repo"
    apply(prompt)
    capsys.readouterr()

    assert apply(prompt, "--verify") == 1

    assert "candidate found 0 times in the request for case case-0" in capsys.readouterr().out
    assert git(repo, "rev-parse", BRANCH) == git(repo, "rev-parse", "main")


def test_verify_commits_the_code_edit_once_the_branch_builds_the_candidate(tmp_path: Path) -> None:
    prompt = code_edit_repo(tmp_path)
    repo = tmp_path / "repo"
    apply(prompt)
    (tmp_path / WORKTREE / "src" / "prompt.txt").write_text("PROMPT = `Be brief. Keep it short.`\n")

    assert apply(prompt, "--verify") == 0

    assert git(repo, "rev-parse", f"{BRANCH}~1") == git(repo, "rev-parse", "main")
    assert git(repo, "diff", "--name-only", f"{BRANCH}~1", BRANCH).splitlines() == ["src/prompt.txt", "whetstone/prompts/daily/editable.txt"]
    assert git(repo, "show", f"{BRANCH}:whetstone/prompts/daily/editable.txt") == "Be brief. Keep it short."
    assert not (tmp_path / WORKTREE).exists()


def test_verify_needs_an_apply_branch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = code_edit_repo(tmp_path)

    assert apply(prompt, "--verify") == 2
    assert "run whetstone apply daily first" in capsys.readouterr().err


def test_a_code_edit_needs_the_workspace_in_the_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = outside_workspace(tmp_path)
    with (prompt / "prompt.toml").open("a") as toml:
        toml.write('apply = "code-edit"\n')
    swiped_run(prompt)

    assert apply(prompt) == 2
    assert "a code edit needs the workspace in the repo" in capsys.readouterr().err
    assert apply_branches(tmp_path / "repo") == ""


def test_the_folder_target_leaves_a_patch_and_the_changed_files(tmp_path: Path) -> None:
    prompt = make_repo(tmp_path)
    repo = tmp_path / "repo"
    swiped_run(prompt)

    assert apply(prompt, "--folder", str(tmp_path / "out")) == 0

    out = tmp_path / "out" / f"daily-{LATER}"
    subprocess.run(["git", "apply", "--check", str(out / "change.patch")], cwd=repo, check=True)
    assert (out / "src" / "prompt.txt").read_text() == "PROMPT = `Be brief. Keep it short.`\n"
    assert (out / "whetstone" / "prompts" / "daily" / "editable.txt").read_text() == "Be brief. Keep it short."
    assert apply_branches(prompt) == ""
    assert len(git(repo, "worktree", "list").splitlines()) == 1


def test_a_deleted_file_is_in_the_patch_but_not_copied(tmp_path: Path) -> None:
    prompt = code_edit_repo(tmp_path)
    repo = tmp_path / "repo"
    (repo / "src" / "old.txt").write_text("gone soon")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "old file")
    out = tmp_path / "out"
    apply(prompt, "--folder", str(out))
    (tmp_path / WORKTREE / "src" / "prompt.txt").write_text("PROMPT = `Be brief. Keep it short.`\n")
    (tmp_path / WORKTREE / "src" / "old.txt").unlink()

    assert apply(prompt, "--verify", "--folder", str(out)) == 0

    export = out / f"daily-{LATER}"
    assert "deleted file mode" in (export / "change.patch").read_text()
    assert not (export / "src" / "old.txt").exists()
    assert (export / "src" / "prompt.txt").is_file()


def test_the_folder_target_defaults_to_the_workspace(tmp_path: Path) -> None:
    prompt = make_repo(tmp_path)
    swiped_run(prompt)

    assert apply(prompt, "--folder") == 0

    assert (tmp_path / "repo" / "whetstone" / ".whetstone" / "applied" / f"daily-{LATER}" / "change.patch").is_file()


def test_an_existing_output_folder_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_repo(tmp_path)
    swiped_run(prompt)
    (tmp_path / "out" / f"daily-{LATER}").mkdir(parents=True)

    assert apply(prompt, "--folder", str(tmp_path / "out")) == 2
    assert f"daily-{LATER} already exists" in capsys.readouterr().err
    assert apply_branches(prompt) == ""
    assert list((tmp_path / "out" / f"daily-{LATER}").iterdir()) == []


def test_a_git_failure_exits_2_with_gits_reason(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_repo(tmp_path)
    hook = tmp_path / "repo" / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'lint failed' >&2\nexit 1\n")
    hook.chmod(0o755)
    swiped_run(prompt)

    assert apply(prompt) == 2
    assert "lint failed" in capsys.readouterr().err
