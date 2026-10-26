import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.test_check_cli import echo_model
from tests.test_judges_cli import judging, make_judged_suite
from whetstone.entry.cli import run
from whetstone.entry.server import make_app
from whetstone.features.checks.core import Agreement, Side, agreement, covered_reasons
from whetstone.features.checks.load import load_judges
from whetstone.features.grading.store import load_labels
from whetstone.features.workspace.load import load_prompt

TOKEN = "t0ken-for-tests"


def test_agreement_counts_a_bad_swipe_whose_reasons_were_filled_from_caught_by(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_judged_suite(tmp_path, {"b": "Why skip it? HRV low."})
    monkeypatch.chdir(tmp_path)
    run(["check", "daily"], make_model=lambda _settings: echo_model(), make_judge=lambda _workspace: judging("yes"))
    [card] = json.loads((tmp_path / ".whetstone" / "decks" / "daily.json").read_text())["cards"]
    client = TestClient(make_app(load_prompt(tmp_path, "daily"), TOKEN))
    client.post("/api/swipes", headers={"Authorization": f"Bearer {TOKEN}"},
                json={"card_id": card["card_id"], "grader": "Levon", "verdict": "bad", "reasons": [], "note": ""})
    labels = load_labels(prompt)

    rows = agreement(labels, {card["card_id"]: False}, covered_reasons({}, load_judges(prompt)))

    # The grader gave no reason; the "assumes" reason on the label is the judge's own catch, copied from caught_by.
    assert rows == {"Levon": Agreement(Side(0, 0), Side(0, 0))}
