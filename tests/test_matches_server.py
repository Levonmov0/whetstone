import json
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from tests.fakes import unused_model
from tests.test_check_cli import echo_model
from tests.test_judges_cli import judging, make_judged_suite
from tests.test_matching_cli import read_lines, swiped, write_labels
from tests.test_server import AUTH, TOKEN
from whetstone.entry.cli import run
from whetstone.entry import server
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
        "reasons": ["assumes", "assumes whether they did Kin's advice", "banned", "length"],
        "sure": [],
    }
    assert [item["id"] for item in client.get("/api/matches", headers={**AUTH, "X-Grader": "Levon"}).json()["items"]] == [match_of(THEIRS)]


def test_yes_makes_the_swipe_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt, client = asked_suite(tmp_path, monkeypatch)

    response = client.post(f"/api/matches/{match_of(NOTE)}", headers=HAMPUS, json={"answer": "yes"})

    assert response.status_code == 200
    line = read_lines(prompt / "labels.jsonl")[-1]
    assert (line["swipe"], line["reasons"], line["verdict"], line["counted"], line["answer"]) == (swipe_id(NOTE), ["banned"], "bad", "confirmed", "yes")
    assert [e["event"] for e in read_lines(prompt / "matches.jsonl")] == ["proposed", "proposed"]
    assert client.get("/api/matches", headers=HAMPUS).json()["items"] == []


def test_no_writes_only_the_answer_and_different_counts_the_picked_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt, client = asked_suite(tmp_path, monkeypatch)

    said_no = client.post(f"/api/matches/{match_of(NOTE)}", headers=HAMPUS, json={"answer": "no"})
    picked = client.post(f"/api/matches/{match_of(THEIRS)}", headers={**AUTH, "X-Grader": "Levon"}, json={"answer": "different", "reason": "length"})

    assert (said_no.status_code, picked.status_code) == (200, 200)
    assert [(e["event"], e["id"], e.get("answer")) for e in read_lines(prompt / "matches.jsonl")][2:] == [("answered", match_of(NOTE), "no")]
    [*_, line] = read_lines(prompt / "labels.jsonl")
    assert (line["swipe"], line["reasons"], line["counted"], line["answer"], line["reason"]) == (swipe_id(THEIRS), ["length"], "confirmed", "different", "length")
    assert len(read_lines(prompt / "labels.jsonl")) == 3


def test_a_second_answer_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt, client = asked_suite(tmp_path, monkeypatch)
    client.post(f"/api/matches/{match_of(NOTE)}", headers=HAMPUS, json={"answer": "yes"})
    before = ((prompt / "labels.jsonl").read_text(), (prompt / "matches.jsonl").read_text())

    again = client.post(f"/api/matches/{match_of(NOTE)}", headers=HAMPUS, json={"answer": "no"})

    assert again.status_code == 200
    assert ((prompt / "labels.jsonl").read_text(), (prompt / "matches.jsonl").read_text()) == before


STALE = "out of date: the card was swiped again, or no check stands for its reasons"


@pytest.mark.parametrize(
    ("change", "match", "body", "status", "error"),
    [
        ("", "theirs", {"answer": "yes"}, 404, "no match {}"),
        ("", "m_nope", {"answer": "yes"}, 404, "no match m_nope"),
        ("reswipe", "mine", {"answer": "yes"}, 409, STALE),
        ("delete check", "mine", {"answer": "yes"}, 409, STALE),
        ("", "mine", {"answer": "different", "reason": "vague"}, 400, 'no check stands for "vague"'),
    ],
)
def test_an_answer_is_refused(change: str, match: str, body: dict[str, Any], status: int, error: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt, client = asked_suite(tmp_path, monkeypatch)
    if change == "reswipe":
        with (prompt / "labels.jsonl").open("a") as f:
            f.write(json.dumps(swiped("c17", verdict="good", note="", at="2026-11-20T09:00:00+00:00")) + "\n")
    if change == "delete check":
        (prompt / "checks" / "banned.py").unlink()
    match = {"mine": match_of(NOTE), "theirs": match_of(THEIRS)}.get(match, match)
    before = ((prompt / "labels.jsonl").read_text(), (prompt / "matches.jsonl").read_text())

    response = client.post(f"/api/matches/{match}", headers=HAMPUS, json=body)

    assert response.status_code == status
    assert response.json() == {"error": error.format(match)}
    assert ((prompt / "labels.jsonl").read_text(), (prompt / "matches.jsonl").read_text()) == before
    assert (client.get("/api/matches", headers=HAMPUS).json()["items"] == []) == bool(change)  # a stale item is hidden too


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ("not json", "body must be a JSON object"),
        ("[1]", "body must be a JSON object"),
        ('{"answer": "maybe"}', "answer must be yes, no, different, undo or redo"),
        ('{"answer": "different"}', "a different chip needs the reason picked"),
        ('{"reason": "' + "x" * 70_000 + '"}', "body is over 64 KB"),
        ('{"answer": "yes", "reason": ["tone"]}', "only a different chip takes a reason"),
        ('{"answer": "no", "reason": "tone"}', "only a different chip takes a reason"),
    ],
)
def test_a_bad_answer_body_is_refused(content: str, error: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt, client = asked_suite(tmp_path, monkeypatch)
    before = (prompt / "matches.jsonl").read_text()

    response = client.post(f"/api/matches/{match_of(NOTE)}", headers={**HAMPUS, "Content-Type": "application/json"}, content=content)

    assert response.status_code == 400
    assert response.json() == {"error": error}
    assert (prompt / "matches.jsonl").read_text() == before


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_a_broken_check_says_so(method: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt, client = asked_suite(tmp_path, monkeypatch)
    (prompt / "checks" / "x.judge.toml").write_text("question = ")
    before = (prompt / "matches.jsonl").read_text()

    response = client.request(method, "/api/matches" if method == "GET" else f"/api/matches/{match_of(NOTE)}", headers=HAMPUS, json={"answer": "yes"})

    assert response.status_code == 500
    assert "checks/x.judge.toml: invalid TOML" in response.json()["error"]
    assert (prompt / "matches.jsonl").read_text() == before


def test_a_waiting_match_survives_a_new_deck_and_a_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prompt, client = asked_suite(tmp_path, monkeypatch)
    client.get("/api/matches", headers=HAMPUS)
    run(["check", "daily"], make_model=lambda _settings: echo_model(), make_judge=lambda _workspace: judging("no"))
    assert (tmp_path / ".whetstone" / "decks" / "daily.json").is_file()
    restarted = TestClient(make_app(load_prompt(tmp_path, "daily"), "a-new-token"))
    fresh = {"Authorization": "Bearer a-new-token", "X-Grader": "Hampus"}

    assert [item["id"] for item in restarted.get("/api/matches", headers=fresh).json()["items"]] == [match_of(NOTE)]
    assert restarted.post(f"/api/matches/{match_of(NOTE)}", headers=fresh, json={"answer": "yes"}).status_code == 200


def test_a_real_data_answer_stays_in_its_private_source_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    private = prompt / "cases" / "private" / "diary"
    noted = swiped("private/diary/day1")
    write_labels(private / "labels.jsonl", [noted])
    monkeypatch.chdir(tmp_path)
    run(["map", "daily", swipe_id(noted), "--reasons", "banned", "--ask", "--why", "Maybe"], make_model=unused_model)
    client = TestClient(make_app(load_prompt(tmp_path, "daily"), TOKEN))

    client.post(f"/api/matches/{match_of(noted)}", headers=HAMPUS, json={"answer": "yes"})

    assert [e["event"] for e in read_lines(private / "matches.jsonl")] == ["proposed"]
    assert len(read_lines(private / "labels.jsonl")) == 2
    assert not (prompt / "matches.jsonl").exists() and not (prompt / "labels.jsonl").exists()


SURE = swiped("c19", note="Says HRV, a banned word")
THEIR_SURE = swiped("c20", grader="Levon", note="Says REM")
LEVON = {**AUTH, "X-Grader": "Levon"}


def sure_suite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, TestClient]:
    """Hampus and Levon each have a note Claude was sure means the banned-words check, besides the asked ones."""
    prompt, client = asked_suite(tmp_path, monkeypatch)
    with (prompt / "labels.jsonl").open("a") as f:
        f.write(json.dumps(SURE) + "\n" + json.dumps(THEIR_SURE) + "\n")
    for label in (SURE, THEIR_SURE):
        run(["map", "daily", swipe_id(label), "--reasons", "banned", "--sure", "--why", "Names a banned word"], make_model=unused_model)
    return prompt, client


def test_a_grader_gets_only_their_own_sure_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prompt, client = sure_suite(tmp_path, monkeypatch)

    assert client.get("/api/matches", headers=HAMPUS).json()["sure"] == [{"id": match_of(SURE), "card_id": "d:c19", "note": "Says HRV, a banned word", "reasons": ["banned"], "undone": False}]
    assert [item["id"] for item in client.get("/api/matches", headers=LEVON).json()["sure"]] == [match_of(THEIR_SURE)]


def test_undo_and_redo_a_sure_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt, client = sure_suite(tmp_path, monkeypatch)
    lines = len(read_lines(prompt / "labels.jsonl"))

    undone = client.post(f"/api/matches/{match_of(SURE)}", headers=HAMPUS, json={"answer": "undo"})

    assert undone.status_code == 200
    line = read_lines(prompt / "labels.jsonl")[-1]
    assert (line["swipe"], line["reasons"], line["verdict"], line["counted"]) == (swipe_id(SURE), [], "bad", "undone")
    assert [e["event"] for e in read_lines(prompt / "matches.jsonl")] == ["proposed"] * 4
    assert client.get("/api/matches", headers=HAMPUS).json()["sure"][0]["undone"] is True

    redone = client.post(f"/api/matches/{match_of(SURE)}", headers=HAMPUS, json={"answer": "redo"})

    assert redone.status_code == 200
    line = read_lines(prompt / "labels.jsonl")[-1]
    assert (line["reasons"], line["counted"]) == (["banned"], "sure")
    assert [e["event"] for e in read_lines(prompt / "matches.jsonl")] == ["proposed"] * 4
    assert len(read_lines(prompt / "labels.jsonl")) == lines + 2
    assert client.get("/api/matches", headers=HAMPUS).json()["sure"][0]["undone"] is False


def test_a_second_undo_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt, client = sure_suite(tmp_path, monkeypatch)
    client.post(f"/api/matches/{match_of(SURE)}", headers=HAMPUS, json={"answer": "undo"})
    before = ((prompt / "labels.jsonl").read_text(), (prompt / "matches.jsonl").read_text())

    again = client.post(f"/api/matches/{match_of(SURE)}", headers=HAMPUS, json={"answer": "undo"})

    assert again.status_code == 200
    assert ((prompt / "labels.jsonl").read_text(), (prompt / "matches.jsonl").read_text()) == before


@pytest.mark.parametrize(
    ("change", "match", "body", "status", "error"),
    [
        ("", THEIR_SURE, {"answer": "undo"}, 404, "no match {}"),
        ("reswipe", SURE, {"answer": "undo"}, 409, STALE),
        ("", SURE, {"answer": "yes"}, 404, "no match {}"),
        ("", NOTE, {"answer": "undo"}, 404, "no match {}"),
    ],
)
def test_an_undo_is_refused(change: str, match: dict[str, Any], body: dict[str, Any], status: int, error: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt, client = sure_suite(tmp_path, monkeypatch)
    if change == "reswipe":
        with (prompt / "labels.jsonl").open("a") as f:
            f.write(json.dumps(swiped("c19", verdict="good", note="", at="2026-11-20T09:00:00+00:00")) + "\n")
    before = ((prompt / "labels.jsonl").read_text(), (prompt / "matches.jsonl").read_text())

    response = client.post(f"/api/matches/{match_of(match)}", headers=HAMPUS, json=body)

    assert response.status_code == status
    assert response.json() == {"error": error.format(match_of(match))}
    assert ((prompt / "labels.jsonl").read_text(), (prompt / "matches.jsonl").read_text()) == before


def test_a_real_data_undo_stays_in_its_private_source_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    private = prompt / "cases" / "private" / "diary"
    noted = swiped("private/diary/day1")
    write_labels(private / "labels.jsonl", [noted])
    monkeypatch.chdir(tmp_path)
    run(["map", "daily", swipe_id(noted), "--reasons", "banned", "--sure", "--why", "Names it"], make_model=unused_model)
    client = TestClient(make_app(load_prompt(tmp_path, "daily"), TOKEN))

    client.post(f"/api/matches/{match_of(noted)}", headers=HAMPUS, json={"answer": "undo"})

    assert [e["event"] for e in read_lines(private / "matches.jsonl")] == ["proposed"]
    assert [line.get("counted") for line in read_lines(private / "labels.jsonl")] == [None, "sure", "undone"]
    assert not (prompt / "matches.jsonl").exists() and not (prompt / "labels.jsonl").exists()


@pytest.mark.parametrize("first", [{"answer": "yes"}, {"answer": "no"}, {"answer": "different", "reason": "assumes"}])
def test_an_answer_says_what_was_stored_even_on_a_repeat(first: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prompt, client = asked_suite(tmp_path, monkeypatch)

    answered = client.post(f"/api/matches/{match_of(NOTE)}", headers=HAMPUS, json=first)
    again = client.post(f"/api/matches/{match_of(NOTE)}", headers=HAMPUS, json={"answer": "yes"} if first["answer"] != "yes" else {"answer": "no"})

    assert answered.json() == first
    assert again.json() == first  # the other phone's answer, which is the one that counts


def test_a_different_chip_left_by_a_crash_is_said_on_the_next_answer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt, client = asked_suite(tmp_path, monkeypatch)
    client.post(f"/api/matches/{match_of(NOTE)}", headers=HAMPUS, json={"answer": "different", "reason": "assumes"})
    events = (prompt / "matches.jsonl").read_text().splitlines()
    (prompt / "matches.jsonl").write_text("".join(line + "\n" for line in events[:-1]))  # died before the event

    again = client.post(f"/api/matches/{match_of(NOTE)}", headers=HAMPUS, json={"answer": "no"})

    assert again.json() == {"answer": "different", "reason": "assumes"}


def test_a_different_chip_claude_also_suggested_is_said_as_different_after_a_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prompt, client = asked_suite(tmp_path, monkeypatch)

    def died(*_args: object) -> None:
        raise OSError("killed")

    with monkeypatch.context() as crash:
        crash.setattr(server, "add_event", died)
        TestClient(client.app, raise_server_exceptions=False).post(f"/api/matches/{match_of(NOTE)}", headers=HAMPUS, json={"answer": "different", "reason": "banned"})

    again = client.post(f"/api/matches/{match_of(NOTE)}", headers=HAMPUS, json={"answer": "no"})

    assert again.json() == {"answer": "different", "reason": "banned"}
