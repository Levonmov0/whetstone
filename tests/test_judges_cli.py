import json
from pathlib import Path

import pytest

from tests.fakes import FakeModel, unused_model
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


def test_proposed_checks_never_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    (prompt / "checks" / "proposed").mkdir()
    (prompt / "checks" / "proposed" / "x.py").write_text("def check(output):\n    return ['always fails']\n")
    (prompt / "checks" / "proposed" / "y.judge.toml").write_text(RUBRIC)
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: echo_model())

    out = capsys.readouterr().out
    assert code == 0
    assert "x:" not in out and "y (judge)" not in out


def test_judge_request_asks_one_question_with_listed_answers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_judged_suite(tmp_path, {"a": "Rest today."})
    judge = judging("no")
    monkeypatch.chdir(tmp_path)

    run(["check", "daily"], make_model=lambda _settings: echo_model(), make_judge=lambda _workspace: judge)

    [request] = judge.requests
    assert request["model"] == "judge-model"
    for part in ("Does the line assume whether the athlete did what Kin advised?", "Asking either way is fine.", '{"text": "Rest today."}', '"Rest today."'):
        assert part in request["input"]
    assert request["text"]["format"] == {
        "type": "json_schema",
        "name": "verdict",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"answer": {"type": "string", "enum": ["no", "yes"]}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    }


MULTIPLE_CHOICE = '''question = "What is wrong with this line, if anything?"
pass = "none"
[fail]
device = "asks about something a watch measures"
instruction = "tells them what to do"
'''


def test_multiple_choice_judge_fails_with_the_chosen_answer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_judged_suite(tmp_path, {"b": "Go skip less."}, MULTIPLE_CHOICE)
    judge = judging("instruction")
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: echo_model(), make_judge=lambda _workspace: judge)

    assert code == 1
    assert judge.requests[0]["text"]["format"]["schema"]["properties"]["answer"]["enum"] == ["none", "device", "instruction"]
    assert "FAIL b: assumes (judge): tells them what to do" in capsys.readouterr().out.splitlines()


@pytest.mark.parametrize(
    ("rubric", "message"),
    [
        ("question = ", "checks/x.judge.toml: invalid TOML"),
        ('pass = "no"\n[fail]\nyes = "bad"\n', 'checks/x.judge.toml: missing "question"'),
        ('question = "Q?"\n[fail]\nyes = "bad"\n', 'checks/x.judge.toml: missing "pass"'),
        ('question = "Q?"\npass = "no"\n[fail]\n', "checks/x.judge.toml: needs at least one failing answer under [fail]"),
        ('question = "Q?"\npass = "no"\n', "checks/x.judge.toml: needs at least one failing answer under [fail]"),
        ('question = "Q?"\npass = "no"\n[fail]\nno = "bad"\n', "checks/x.judge.toml: \"no\" can't be both the passing answer and a failing one"),
        ('question = "Q?"\npass = "no"\n[fail]\nyes = 3\n', "checks/x.judge.toml: [fail] maps each failing answer to its reason text"),
        ('question = "Q?"\npass = "no"\nguide = 3\n[fail]\nyes = "bad"\n', "checks/x.judge.toml: guide must be text"),
        ('question = "Q?"\npass = "no"\nreasons = "bad"\n[fail]\nyes = "bad"\n', "checks/x.judge.toml: reasons must be a list of text"),
    ],
)
def test_bad_rubric_stops_before_any_model_call(
    rubric: str, message: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    (prompt / "checks" / "x.judge.toml").write_text(rubric)
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model, make_judge=unused_model)

    assert code == 2
    assert message in capsys.readouterr().err


def test_judge_named_like_a_code_check_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    (prompt / "checks" / "banned.judge.toml").write_text(RUBRIC)
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model, make_judge=unused_model)

    assert code == 2
    assert "check banned is both banned.py and banned.judge.toml" in capsys.readouterr().err


@pytest.mark.parametrize(
    "settings",
    [
        "",
        "models = 3\n",
        "[models]\n",
        '[models]\njudge = { provider = "anthropic", model = "judge-model" }\n',
        '[models]\njudge = { provider = "openai" }\n',
        '[models]\njudge = "gpt"\n',
    ],
)
def test_judges_need_an_openai_judge_model(settings: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_judged_suite(tmp_path, {"a": "Rest today."})
    (tmp_path / "whetstone.toml").write_text(settings)
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model, make_judge=unused_model)

    assert code == 2
    assert 'whetstone.toml: [models] judge needs provider = "openai" and a model' in capsys.readouterr().err
