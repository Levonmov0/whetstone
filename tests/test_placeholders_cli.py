import json
from pathlib import Path

import pytest

from tests.fakes import FakeModel, unused_model
from tests.test_check_cli import make_prompt, make_workspace
from tests.test_run_cli import HARNESS, make_run_suite, rewriter, run_folder, start_run, writer
from whetstone.entry.cli import run


def harness_building(system: str) -> str:
    body = {"model": "fake-model", "system": system, "messages": [{"role": "user", "content": "Day 1."}]}
    return f"import json; print(json.dumps({body!r}))"


@pytest.mark.parametrize("table", ['[placeholders]\n"${VOICE}" = 3\n', 'placeholders = "x"\n'])
def test_a_placeholder_table_must_map_text_to_text(table: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_prompt(make_workspace(tmp_path), harness_building("Be brief."), {"first-day": {}})
    with (prompt / "prompt.toml").open("a") as toml:
        toml.write(table)
    monkeypatch.chdir(tmp_path)

    assert run(["check", "daily"], make_model=unused_model) == 2
    err = capsys.readouterr().err
    assert "prompt.toml" in err and "placeholders" in err


@pytest.mark.parametrize("method", ["placeholders", "anything"])
def test_apply_is_exact_or_code_edit(method: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_prompt(make_workspace(tmp_path), harness_building("Be brief."), {"first-day": {}})
    with (prompt / "prompt.toml").open("a") as toml:
        toml.write(f'apply = "{method}"\n')
    monkeypatch.chdir(tmp_path)

    assert run(["check", "daily"], make_model=unused_model) == 2
    assert 'apply must be "exact" or "code-edit"' in capsys.readouterr().err


def voice_prompt(workspace: Path) -> Path:
    """Editable `Be brief. ${VOICE}`, whose ${VOICE} is built as `Speak plainly.`"""
    prompt = make_prompt(make_workspace(workspace), harness_building("Be brief. Speak plainly."), {"first-day": {}})
    (prompt / "editable.txt").write_text("Be brief. ${VOICE}")
    with (prompt / "prompt.toml").open("a") as toml:
        toml.write('[placeholders]\n"${VOICE}" = "Speak plainly."\n')
    return prompt


def test_placeholders_are_expanded_before_the_editable_part_is_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    voice_prompt(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert run(["check", "daily"], make_model=lambda _settings: FakeModel(lambda _request: "ok")) == 0


def test_a_run_sends_expanded_text_and_keeps_placeholders_in_its_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_run_suite(tmp_path)
    (prompt / "harness.py").write_text(HARNESS.replace("Be brief.", "Be brief. Speak plainly."))
    (prompt / "editable.txt").write_text("Be brief. ${VOICE}")
    with (prompt / "prompt.toml").open("a") as toml:
        toml.write('[placeholders]\n"${VOICE}" = "Speak plainly."\n')
    model = writer()
    monkeypatch.chdir(tmp_path)

    assert start_run(model, rewriter("Be brief. ${VOICE} Keep it short.")) == 0

    assert model.requests
    assert all("${VOICE}" not in json.dumps(request) and "Speak plainly." in request["system"] for request in model.requests)
    assert (run_folder(prompt) / "candidate.txt").read_text() == "Be brief. ${VOICE} Keep it short."


def test_a_rewrite_that_drops_a_table_placeholder_never_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_run_suite(tmp_path)
    (prompt / "harness.py").write_text(HARNESS.replace("Be brief.", "Be brief. Speak plainly."))
    (prompt / "editable.txt").write_text("Be brief. VOICE_RULES")
    with (prompt / "prompt.toml").open("a") as toml:
        toml.write('[placeholders]\nVOICE_RULES = "Speak plainly."\n')
    model = writer()
    monkeypatch.chdir(tmp_path)

    assert start_run(model, rewriter("Be brief. Keep it short.")) == 1
    assert all(request["system"] == "Be brief. Speak plainly." for request in model.requests)
