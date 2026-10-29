import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeModel, unused_model
from tests.test_check_cli import echo_model, make_suite
from whetstone.entry.cli import production_judge, run
from whetstone.platform.model import ModelError

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
def test_judges_need_a_known_judge_provider_and_model(settings: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_judged_suite(tmp_path, {"a": "Rest today."})
    (tmp_path / "whetstone.toml").write_text(settings)
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model, make_judge=unused_model)

    assert code == 2
    assert 'whetstone.toml: [models] judge needs provider = "openai" or "cloudflare", and a model' in capsys.readouterr().err


def test_missing_judge_key_stops_before_any_model_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_judged_suite(tmp_path, {"a": "Rest today."})
    (tmp_path / ".env").write_text("GENERATION_API_KEY=k\n")
    monkeypatch.setenv("JUDGE_API_KEY", "shell-key")  # the shell's never counts
    model = echo_model()
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: model, make_judge=production_judge)

    assert code == 2
    assert f"JUDGE_API_KEY is not set in {tmp_path / '.env'}" in capsys.readouterr().err
    assert model.requests == []


def add_private_case(prompt: Path) -> None:
    source = prompt / "cases" / "private" / "diary"
    source.mkdir(parents=True)
    (source / "consent.toml").write_text('consented_by = "Levon"\nconsented_on = 2026-10-26\n')
    (source / "day1.json").write_text(json.dumps({"text": "Slept badly."}))


@pytest.mark.parametrize(("providers", "code"), [('["anthropic"]', 2), ('["anthropic", "openai"]', 0)])
def test_real_data_reaches_judges_only_on_a_provider_the_repo_uses(
    providers: str, code: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    add_private_case(prompt)
    (tmp_path / "whetstone.toml").write_text(f"repo_providers = {providers}\n" + JUDGE_SETTINGS)
    model, judge = echo_model(), judging("no")
    monkeypatch.chdir(tmp_path)

    assert run(["check", "daily"], make_model=lambda _settings: model, make_judge=lambda _workspace: judge) == code

    if code == 2:
        assert "real-data cases go only to providers this repo already uses (anthropic); openai is not one" in capsys.readouterr().err
        assert model.requests == [] and judge.requests == []


def failing_judge(_request: dict[str, object]) -> str:
    raise ModelError("RateLimitError 429")


def replying(text: str) -> Callable[[dict[str, object]], str]:
    return lambda _request: text


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (failing_judge, "judge assumes failed on case b: RateLimitError 429"),
        (replying("not json"), 'judge assumes answered "not json" on case b; expected one of: no, yes'),
        (replying('{"answer": "maybe"}'), 'judge assumes answered "maybe" on case b; expected one of: no, yes'),
        (replying('["yes"]'), 'judge assumes answered "[\\"yes\\"]" on case b; expected one of: no, yes'),
    ],
)
def test_unusable_judge_answer_stops_and_keeps_the_deck(
    answer: Callable[[dict[str, object]], str], message: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_judged_suite(tmp_path, {"b": "Why did you skip it?"})
    monkeypatch.chdir(tmp_path)
    run(["check", "daily"], make_model=lambda _settings: echo_model(), make_judge=lambda _workspace: judging("no"))
    deck = tmp_path / ".whetstone" / "decks" / "daily.json"
    before = deck.read_text()

    code = run(["check", "daily"], make_model=lambda _settings: echo_model(), make_judge=lambda _workspace: FakeModel(answer))

    assert code == 2
    assert message in capsys.readouterr().err
    assert deck.read_text() == before


def test_call_counts_are_printed_before_the_first_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_judged_suite(tmp_path, {"a": "Rest today.", "b": "Walk later."})
    printed_before: list[str] = []

    def generate(request: dict[str, object]) -> object:
        if not printed_before:
            printed_before.append(capsys.readouterr().out)
        return echo_model().answer(request)

    monkeypatch.chdir(tmp_path)

    run(["check", "daily"], make_model=lambda _settings: FakeModel(generate), make_judge=lambda _workspace: judging("no"))

    assert printed_before == ["2 generation calls and 2 judge calls\n"]


def test_call_count_without_judges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_suite(tmp_path, {"a": "Rest today."})
    monkeypatch.chdir(tmp_path)

    run(["check", "daily"], make_model=lambda _settings: echo_model())

    assert capsys.readouterr().out.splitlines()[0] == "1 generation call"


CLOUDFLARE_SETTINGS = '[models]\njudge = { provider = "cloudflare", model = "@cf/cloudflare/clef" }\n'


def clef_choosing(answer: str) -> FakeModel:
    """A Clef judge choosing `answer` on outputs that mention skipping, else "none"."""
    def choose(request: dict[str, Any]) -> dict[str, Any]:
        choice = answer if "skip" in json.dumps(request["state"]) else "none"
        return {"model": "clef", "answers": {"verdict": {"type": "choice", "choice": choice, "probabilities": {choice: 1.0}, "confidence": 1.0}}, "usage": {"input_tokens": 1, "output_tokens": 0}}
    return FakeModel(choose)


def test_a_cloudflare_judge_asks_clef_one_choice_question(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_judged_suite(tmp_path, {"a": "Rest today.", "b": "Go skip less."}, MULTIPLE_CHOICE)
    (tmp_path / "whetstone.toml").write_text(CLOUDFLARE_SETTINGS)
    judge = clef_choosing("instruction")
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: echo_model(), make_judge=lambda _workspace: judge)

    assert code == 1
    assert "FAIL b: assumes (judge): tells them what to do" in capsys.readouterr().out.splitlines()
    request = judge.requests[0]
    assert request["model"] == "@cf/cloudflare/clef"
    # The output first, so a state Clef truncates to fit its window loses input, never the output it judges.
    assert list(request["state"]) == ["output", "input"]
    assert request["state"] == {"output": "Rest today.", "input": {"text": "Rest today."}}
    [question] = request["questions"].values()
    assert question["type"] == "choice"
    assert "What is wrong with this line, if anything?" in question["instructions"]
    assert question["criteria"] == {"none": None, "device": "asks about something a watch measures", "instruction": "tells them what to do"}


def test_a_clef_choice_outside_the_rubric_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_judged_suite(tmp_path, {"b": "Go skip less."})
    (tmp_path / "whetstone.toml").write_text(CLOUDFLARE_SETTINGS)
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: echo_model(), make_judge=lambda _workspace: clef_choosing("maybe"))

    assert code == 2
    assert 'judge assumes answered "maybe" on case b; expected one of: no, yes' in capsys.readouterr().err


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ("JUDGE_API_KEY=sk-openai\n", "JUDGE_CF_ACCOUNT_ID is not set in"),
        ("JUDGE_CF_ACCOUNT_ID=0123456789abcdef0123456789abcdef\n", "JUDGE_CF_API_TOKEN is not set in"),
        ("JUDGE_CF_ACCOUNT_ID=../../evil\nJUDGE_CF_API_TOKEN=t\n", "JUDGE_CF_ACCOUNT_ID in"),
    ],
)
def test_a_cloudflare_judge_needs_its_own_keys(env: str, message: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_judged_suite(tmp_path, {"a": "Rest today."})
    (tmp_path / "whetstone.toml").write_text(CLOUDFLARE_SETTINGS)
    (tmp_path / ".env").write_text(env)
    model = echo_model()
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: model, make_judge=production_judge)

    assert code == 2
    assert message in capsys.readouterr().err
    assert model.requests == []


def test_real_data_reaches_a_cloudflare_judge_only_when_the_repo_uses_cloudflare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    add_private_case(prompt)
    (tmp_path / "whetstone.toml").write_text('repo_providers = ["anthropic", "openai"]\n' + CLOUDFLARE_SETTINGS)
    judge = clef_choosing("yes")
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: echo_model(), make_judge=lambda _workspace: judge)

    assert code == 2
    assert "real-data cases go only to providers this repo already uses (anthropic, openai); cloudflare is not one" in capsys.readouterr().err
    assert judge.requests == []
