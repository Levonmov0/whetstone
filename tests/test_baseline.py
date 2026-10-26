import json
import random
import re
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeModel
from tests.test_check_cli import make_suite
from tests.test_judges_cli import JUDGE_SETTINGS, add_private_case, judging, make_judged_suite
from whetstone.entry.cli import production_judge, run
from whetstone.platform.model import ModelError


def by_model() -> FakeModel:
    """Echoes the case text, in capitals from model-b, so a card shows which model wrote it without naming it."""
    def answer(request: dict[str, Any]) -> str:
        text = request["messages"][0]["content"]
        return text.upper() if request["model"] == "model-b" else text
    return FakeModel(answer)


def test_baseline_runs_every_case_on_every_model_into_one_blind_deck(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_suite(tmp_path, {"a": "Rest today.", "b": "Walk later.", "c": "Sleep early."})
    model = by_model()
    random.seed(1)
    monkeypatch.chdir(tmp_path)

    code = run(["baseline", "daily", "--models", "model-b"], make_model=lambda _settings: model)

    assert code == 0
    assert sorted(r["model"] for r in model.requests) == ["fake-model"] * 3 + ["model-b"] * 3
    same_otherwise = {json.dumps({**r, "model": None}, sort_keys=True) for r in model.requests}
    assert len(same_otherwise) == 3
    deck = json.loads((tmp_path / ".whetstone" / "decks" / "daily.json").read_text())
    ids = [card["card_id"] for card in deck["cards"]]
    assert len(set(ids)) == 6
    assert all(re.fullmatch(rf"{deck['id']}:[abc]:[0-9a-f]{{8}}", card_id) for card_id in ids)
    assert "fake-model" not in json.dumps(deck["cards"]) and "model-b" not in json.dumps(deck["cards"])
    from_b = [card["output"].isupper() for card in deck["cards"]]
    assert from_b not in ([False] * 3 + [True] * 3, [True] * 3 + [False] * 3)


def test_baseline_keeps_which_model_wrote_each_card_in_its_run_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today.", "b": "Walk later.", "c": "Sleep early."})
    monkeypatch.chdir(tmp_path)

    run(["baseline", "daily", "--models", "model-b"], make_model=lambda _settings: by_model())

    deck = json.loads((tmp_path / ".whetstone" / "decks" / "daily.json").read_text())
    folder = prompt / "runs" / f"baseline-{deck['id']}"
    sources = json.loads((folder / "cards.json").read_text())
    assert sources == {card["card_id"]: "model-b" if card["output"].isupper() else "fake-model" for card in deck["cards"]}
    assert "rest today" not in (folder / "cards.json").read_text().lower()  # model names only, never outputs
    assert (folder / "report.md").is_file()


def test_baseline_report_has_the_verdict_and_a_row_per_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today.", "b": "Your HRV is low.", "c": "Why skip it?"})
    monkeypatch.chdir(tmp_path)

    run(["baseline", "daily", "--models", "model-b"], make_model=lambda _settings: by_model(), make_judge=lambda _workspace: judging("yes"))

    [report] = (prompt / "runs").glob("baseline-*/report.md")
    lines = report.read_text().splitlines()
    assert "No: no listed model fixes most failures. The best, model-b, passes 0 of the 2 cases fake-model fails. The prompt is the problem." in lines
    assert "| model | every check | banned | length | assumes (judge) | input tokens | output tokens |" in lines
    assert "| fake-model | 1/3 | 2/3 | 3/3 | 2/3 | 30 | 15 |" in lines
    assert "| model-b | 1/3 | 2/3 | 3/3 | 2/3 | 30 | 15 |" in lines


def test_baseline_report_adds_the_swipes_per_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today.", "b": "Walk later."})
    monkeypatch.chdir(tmp_path)
    run(["baseline", "daily", "--models", "model-b"], make_model=lambda _settings: by_model())
    deck = json.loads((tmp_path / ".whetstone" / "decks" / "daily.json").read_text())
    [folder] = (prompt / "runs").glob("baseline-*")
    sources = json.loads((folder / "cards.json").read_text())
    by = {model: [card for card in deck["cards"] if sources[card["card_id"]] == model] for model in ("fake-model", "model-b")}

    def swipe(card: dict[str, Any], verdict: str, grader: str = "Levon", at: str = "2026-10-26T08:00:00+00:00") -> str:
        return json.dumps({**card, "deck_id": deck["id"], "grader": grader, "verdict": verdict, "reasons": [], "note": "", "at": at}) + "\n"

    (prompt / "labels.jsonl").write_text(
        swipe(by["fake-model"][0], "bad")
        + swipe(by["fake-model"][0], "good", at="2026-10-26T09:00:00+00:00")  # Levon changed his mind: only this counts
        + swipe(by["fake-model"][1], "good")
        + swipe(by["fake-model"][1], "bad", grader="Hampus")
        + swipe(by["model-b"][0], "skip")
        + json.dumps({"card_id": "older:a", "grader": "Levon", "verdict": "bad", "reasons": [], "note": "", "at": "1"}) + "\n"
    )

    first = run(["baseline", "daily", "--report"], make_model=lambda _settings: by_model())
    code = run(["baseline", "daily", "--report"], make_model=lambda _settings: by_model())  # rewritten, not appended

    lines = (folder / "report.md").read_text().splitlines()
    assert (first, code) == (0, 0)
    assert "fake-model passes every check on every case; a model change has nothing to fix." in lines
    assert lines.count("## Swipes") == 1
    assert "- fake-model: good 2, bad 1, skip 0" in lines
    assert "- model-b: good 0, bad 0, skip 1" in lines


def test_baseline_report_without_a_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_suite(tmp_path, {"a": "Rest today."})
    monkeypatch.chdir(tmp_path)

    code = run(["baseline", "daily", "--report"], make_model=lambda _settings: by_model())

    assert code == 2
    assert "no baseline run for daily yet; run whetstone baseline daily --models …" in capsys.readouterr().err


@pytest.mark.parametrize("models", [[], ["--models", "fake-model"], ["--models", ","]])
def test_baseline_needs_another_model(models: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_suite(tmp_path, {"a": "Rest today."})
    model = by_model()
    monkeypatch.chdir(tmp_path)

    code = run(["baseline", "daily", *models], make_model=lambda _settings: model)

    assert code == 2
    assert "--models needs at least one model besides fake-model" in capsys.readouterr().err
    assert model.requests == []


def test_baseline_runs_production_once_and_says_its_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_suite(tmp_path, {"a": "Rest today."})
    model = by_model()
    monkeypatch.chdir(tmp_path)

    run(["baseline", "daily", "--models", "fake-model,model-b"], make_model=lambda _settings: model)

    assert [r["model"] for r in model.requests] == ["fake-model", "model-b"]
    assert capsys.readouterr().out.splitlines()[0] == "2 generation calls"


def test_a_failing_model_stops_the_baseline_and_keeps_the_deck(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    monkeypatch.chdir(tmp_path)
    run(["check", "daily"], make_model=lambda _settings: by_model())
    deck = tmp_path / ".whetstone" / "decks" / "daily.json"
    before = deck.read_text()

    def answer(request: dict[str, Any]) -> str:
        if request["model"] == "model-b":
            raise ModelError("BadRequestError 400")
        return "Rest today."

    code = run(["baseline", "daily", "--models", "model-b"], make_model=lambda _settings: FakeModel(answer))

    assert code == 2
    assert "model-b failed on case a: BadRequestError 400" in capsys.readouterr().err
    assert deck.read_text() == before
    assert not (prompt / "runs").exists()


@pytest.mark.parametrize("broken", ["consent", "provider", "harness", "judge key"])
def test_baseline_vets_the_suite_like_check(broken: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    message = {
        "consent": "real-data case private/diary/day1 has no consent record; run whetstone add-source",
        "provider": "real-data cases go only to providers this repo already uses (openai); anthropic is not one",
        "harness": "case a: ",
        "judge key": f"JUDGE_API_KEY is not set in {tmp_path / '.env'}",
    }[broken]
    if broken in ("consent", "provider"):
        add_private_case(prompt)
    if broken == "consent":
        (prompt / "cases" / "private" / "diary" / "consent.toml").unlink()
    if broken == "provider":
        (tmp_path / "whetstone.toml").write_text('repo_providers = ["openai"]\n' + JUDGE_SETTINGS)
    if broken == "harness":
        (prompt / "harness.py").write_text("import sys; sys.exit(3)")
    model = by_model()
    monkeypatch.chdir(tmp_path)

    code = run(["baseline", "daily", "--models", "model-b"], make_model=lambda _settings: model, make_judge=production_judge)

    assert code == 2
    assert message in capsys.readouterr().err
    assert model.requests == []
