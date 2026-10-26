import json
from pathlib import Path

import pytest

from tests.fakes import FakeModel
from tests.test_check_cli import echo_model, make_suite
from whetstone.entry.cli import run

RUBRIC = '''question = "Does the line assume whether the athlete did what Kin advised?"
guide = "Asking either way is fine."
pass = "no"
[fail]
yes = "assumes whether they did Kin's advice"
'''

JUDGE_SETTINGS = '[models]\njudge = { provider = "openai", model = "judge-model" }\n'


def make_judged_suite(tmp_path: Path, cases: dict[str, str], rubric: str = RUBRIC) -> Path:
    prompt = make_suite(tmp_path, cases)
    (tmp_path / "whetstone.toml").write_text(JUDGE_SETTINGS)
    (prompt / "checks" / "assumes.judge.toml").write_text(rubric)
    return prompt


def judging(answer: str) -> FakeModel:
    """A judge answering `answer` on outputs that mention skipping, else "no"."""
    return FakeModel(lambda request: json.dumps({"answer": answer if "skip" in json.dumps(request) else "no"}))


def test_check_runs_judges_beside_code_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_judged_suite(tmp_path, {"a": "Rest today.", "b": "Why did you skip it?"})
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: echo_model(), make_judge=lambda _workspace: judging("yes"))

    out = capsys.readouterr().out.splitlines()
    assert code == 1
    assert "PASS a" in out
    assert "FAIL b: assumes (judge): assumes whether they did Kin's advice" in out
    assert "assumes (judge): 1/2" in out
    assert "length: 2/2" in out
    deck = json.loads((tmp_path / ".whetstone" / "decks" / "daily.json").read_text())
    assert [card["caught_by"] for card in deck["cards"]] == [[], ["assumes"]]
