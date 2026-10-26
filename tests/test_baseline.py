import json
import random
import re
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeModel
from tests.test_check_cli import make_suite
from tests.test_judges_cli import judging, make_judged_suite
from whetstone.entry.cli import run


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
    assert "| model | every check | length | banned | assumes (judge) | input tokens | output tokens |" in lines
    assert "| fake-model | 1/3 | 3/3 | 2/3 | 2/3 | 30 | 15 |" in lines
    assert "| model-b | 1/3 | 3/3 | 2/3 | 2/3 | 30 | 15 |" in lines
