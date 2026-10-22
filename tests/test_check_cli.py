import json
import sys
from pathlib import Path

import httpx2 as httpx
import pytest

from tests.fakes import FakeModel, unused_model
from whetstone.entry.cli import production_model, run
from whetstone.platform.anthropic import anthropic_model


def test_no_workspace_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model)

    assert code == 2
    assert "no Whetstone workspace found; run /whetstone:init or pass --workspace" in capsys.readouterr().err


def make_prompt_dir(workspace: Path, name: str) -> Path:
    prompt = workspace / "prompts" / name
    prompt.mkdir(parents=True)
    return prompt


@pytest.mark.parametrize("layout", ["here", "subfolder", "flag"])
def test_unknown_prompt_lists_the_known_ones(
    layout: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = {"here": tmp_path, "subfolder": tmp_path / "whetstone", "flag": tmp_path / "elsewhere"}[layout]
    workspace.mkdir(exist_ok=True)
    (workspace / "whetstone.toml").write_text("")
    make_prompt_dir(workspace, "b")
    make_prompt_dir(workspace, "a")
    monkeypatch.chdir(tmp_path)
    argv = ["check", "daily"] + (["--workspace", str(workspace)] if layout == "flag" else [])

    code = run(argv, make_model=unused_model)

    assert code == 2
    assert "no prompt named daily; prompts: a, b" in capsys.readouterr().err


def make_workspace(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "whetstone.toml").write_text("")
    return root


def make_prompt(workspace: Path, harness: str, cases: dict[str, object], name: str = "daily", model: str = "fake-model") -> Path:
    """A prompt whose harness is the given Python source, run with this interpreter."""
    prompt = make_prompt_dir(workspace, name)
    (prompt / "harness.py").write_text(harness)
    settings = {
        "harness": f"{sys.executable} prompts/{name}/harness.py",
        "editable": "Be brief.",
        "provider": "anthropic",
        "model": model,
    }
    (prompt / "prompt.toml").write_text("".join(f"{k} = {json.dumps(v)}\n" for k, v in settings.items()))
    (prompt / "cases").mkdir()
    for case_id, case in cases.items():
        (prompt / "cases" / f"{case_id}.json").write_text(json.dumps(case))
    return prompt


@pytest.mark.parametrize(
    ("harness", "reason"),
    [
        ("import sys; print('builder exploded', file=sys.stderr); sys.exit(3)", "builder exploded"),
        ("print('not json')", "harness printed invalid JSON"),
    ],
)
def test_broken_harness_stops_before_any_model_call(
    harness: str, reason: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_prompt(make_workspace(tmp_path), harness, {"first-day": {"day": 1}})
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model)

    err = capsys.readouterr().err
    assert code == 2
    assert "first-day" in err
    assert reason in err


@pytest.mark.parametrize(
    ("request_body", "missing"),
    [
        ({"messages": [{"role": "user", "content": "Be brief."}]}, "model"),
        ({"model": "fake-model", "system": "Be brief."}, "messages"),
    ],
)
def test_request_missing_a_required_field(
    request_body: dict[str, object], missing: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_prompt(make_workspace(tmp_path), f"import json; print(json.dumps({request_body!r}))", {"first-day": {}})
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model)

    assert code == 2
    assert f'harness request for case first-day is missing "{missing}"' in capsys.readouterr().err


def test_harness_model_must_match_the_recorded_production_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    request = {"model": "other-model", "messages": [{"role": "user", "content": "Be brief."}]}
    make_prompt(make_workspace(tmp_path), f"import json; print(json.dumps({request!r}))", {"first-day": {}})
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model)

    assert code == 2
    assert "harness requests other-model but prompt.toml records production model fake-model" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("request_body", "times"),
    [
        ({"model": "fake-model", "system": "Write a card.", "messages": [{"role": "user", "content": "Day 1."}]}, 0),
        (
            {
                "model": "fake-model",
                "system": [{"type": "text", "text": "Be brief. Write a card."}],
                "messages": [{"role": "user", "content": [{"type": "text", "text": "Day 1. Be brief."}]}],
            },
            2,
        ),
    ],
)
def test_editable_part_must_appear_exactly_once(
    request_body: dict[str, object], times: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_prompt(make_workspace(tmp_path), f"import json; print(json.dumps({request_body!r}))", {"first-day": {}})
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model)

    assert code == 2
    assert f"editable part found {times} times in request for case first-day" in capsys.readouterr().err


ECHO_HARNESS = """
import json, sys
case = json.load(sys.stdin)
print(json.dumps({"model": "fake-model", "max_tokens": 50, "system": "Be brief.",
                  "messages": [{"role": "user", "content": case["text"]}]}))
"""

CHECKS = {
    "length": "def check(output):\n    return [f'Is {len(output)} characters (max 40).'] if len(output) > 40 else []\n",
    "banned": "def check(output):\n    return ['Uses banned term HRV.'] if 'HRV' in output else []\n",
}


def make_suite(tmp_path: Path, cases: dict[str, str]) -> Path:
    prompt = make_prompt(make_workspace(tmp_path), ECHO_HARNESS, {k: {"text": v} for k, v in cases.items()})
    (prompt / "checks").mkdir()
    for name, source in CHECKS.items():
        (prompt / "checks" / f"{name}.py").write_text(source)
    return prompt


def echo_model() -> FakeModel:
    return FakeModel(lambda request: request["messages"][0]["content"])


def test_check_reports_each_case_and_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_suite(tmp_path, {"a": "Rest today.", "b": "Your HRV is low."})
    model = echo_model()
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: model)

    out = capsys.readouterr().out.splitlines()
    assert code == 1
    assert "PASS a" in out
    assert "FAIL b: banned: Uses banned term HRV." in out
    assert "length: 2/2" in out
    assert "banned: 1/2" in out
    assert "1 of 2 cases pass every check" in out
    assert model.requests == [
        {"model": "fake-model", "max_tokens": 50, "system": "Be brief.", "messages": [{"role": "user", "content": text}]}
        for text in ("Rest today.", "Your HRV is low.")
    ]


def test_check_exits_0_when_every_case_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_suite(tmp_path, {"a": "Rest today.", "b": "Walk later."})
    model = echo_model()
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: model)

    assert code == 0
    assert "2 of 2 cases pass every check" in capsys.readouterr().out.splitlines()


def test_a_crashing_check_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today.", "b": "Walk later."})
    (prompt / "checks" / "banned.py").write_text("def check(output):\n    if 'Walk' in output:\n        raise ValueError('no rule for walks')\n    return []\n")
    model = echo_model()
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: model)

    assert code == 2
    assert "check banned crashed on case b: no rule for walks" in capsys.readouterr().err


def test_missing_generation_key_names_the_variable_and_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_suite(tmp_path, {"a": "Rest today."})
    (tmp_path / ".env").write_text("JUDGE_API_KEY=sk-judge-secret\n")
    monkeypatch.setenv("GENERATION_API_KEY", "sk-from-the-shell")  # only the workspace file counts
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=production_model)

    captured = capsys.readouterr()
    assert code == 2
    assert f"GENERATION_API_KEY is not set in {tmp_path / '.env'}" in captured.err
    assert "sk-" not in captured.out + captured.err


def test_a_failed_model_call_exits_2_without_the_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_suite(tmp_path, {"a": "Rest today."})
    unauthorized = httpx.MockTransport(lambda _r: httpx.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}))
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=lambda _settings: anthropic_model("sk-wrong-key-123", transport=unauthorized))

    captured = capsys.readouterr()
    assert code == 2
    assert "model call failed on case a" in captured.err
    assert "sk-wrong-key-123" not in captured.out + captured.err


@pytest.mark.parametrize(
    ("toml", "reason"),
    [
        ('harness = "x"\nmodel = "m"\neditable = "e"\n', 'missing "provider"'),
        ('harness = "x\n', "invalid TOML"),
    ],
)
def test_a_broken_prompt_toml_exits_2(
    toml: str, reason: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (make_prompt_dir(make_workspace(tmp_path), "daily") / "prompt.toml").write_text(toml)
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model)

    err = capsys.readouterr().err
    assert code == 2
    assert f"{tmp_path / 'prompts' / 'daily' / 'prompt.toml'}: {reason}" in err


def test_a_workspace_with_no_prompts_yet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model)

    assert code == 2
    assert "no prompt named daily; prompts: none yet" in capsys.readouterr().err


def test_a_prompt_with_no_cases_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_prompt(make_workspace(tmp_path), ECHO_HARNESS, {})
    monkeypatch.chdir(tmp_path)

    code = run(["check", "daily"], make_model=unused_model)

    assert code == 2
    assert f"no cases in {tmp_path / 'prompts' / 'daily' / 'cases'}" in capsys.readouterr().err
