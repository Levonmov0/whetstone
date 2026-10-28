import json
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


@pytest.fixture(autouse=True)
def plain_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Git without the user's own config (signing, hooks), and with a committer."""
    (tmp_path / "gitconfig").write_text("[user]\n\tname = Tester\n\temail = tester@example.com\n[init]\n\tdefaultBranch = main\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


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
