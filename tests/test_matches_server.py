import json
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from tests.fakes import unused_model
from tests.test_judges_cli import make_judged_suite
from tests.test_matching_cli import read_lines, swiped, write_labels
from tests.test_server import AUTH, TOKEN
from whetstone.entry.cli import run
from whetstone.entry.server import make_app
from whetstone.features.matching.core import swipe_id
from whetstone.features.workspace.load import load_prompt

HAMPUS = {**AUTH, "X-Grader": "Hampus"}
NOTE = swiped("c17", note="Feels like a horoscope", output="Today is a chance to reset.")
THEIRS = swiped("c18", grader="Levon", note="Too clinical")


def match_of(label: dict[str, Any]) -> str:
    return "m_" + swipe_id(label).removeprefix("s_")


def asked_suite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, TestClient]:
    """Hampus and Levon each have a note Claude asked about, suggesting the banned-words check."""
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    write_labels(prompt / "labels.jsonl", [NOTE, THEIRS])
    monkeypatch.chdir(tmp_path)
    for label in (NOTE, THEIRS):
        run(["map", "daily", swipe_id(label), "--reasons", "banned", "--ask", "--why", "Might be the banned words"], make_model=unused_model)
    return prompt, TestClient(make_app(load_prompt(tmp_path, "daily"), TOKEN))


@pytest.mark.parametrize(("method", "path"), [("GET", "/api/matches"), ("POST", "/api/matches/m_1")])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_matches_need_the_token(method: str, path: str, headers: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prompt, client = asked_suite(tmp_path, monkeypatch)

    response = client.request(method, path, headers={"X-Grader": "Hampus", **headers}, json={"answer": "yes"})

    assert response.status_code == 401
    assert response.json() == {"error": "missing or wrong token"}


def test_a_grader_gets_only_their_own_waiting_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prompt, client = asked_suite(tmp_path, monkeypatch)

    response = client.get("/api/matches", headers=HAMPUS)

    assert response.status_code == 200
    assert response.json() == {
        "items": [{"id": match_of(NOTE), "card_id": "d:c17", "note": "Feels like a horoscope", "excerpt": "Today is a chance to reset.", "reasons": ["banned"], "why": "Might be the banned words"}],
        "reasons": ["assumes", "assumes whether they did Kin's advice", "banned"],
    }
    assert [item["id"] for item in client.get("/api/matches", headers={**AUTH, "X-Grader": "Levon"}).json()["items"]] == [match_of(THEIRS)]
