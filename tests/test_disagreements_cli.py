import json
from pathlib import Path

import pytest

from tests.fakes import unused_model
from tests.test_check_cli import make_suite
from whetstone.entry.cli import run


def label(card: str, grader: str, verdict: str, reasons: list[str] | None = None, note: str = "") -> dict[str, object]:
    return {"card_id": card, "case_id": card.split(":")[1], "grader": grader, "verdict": verdict, "reasons": reasons or [], "note": note}


def write_labels(path: Path, labels: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in labels))


def test_disagreements_lists_each_card_to_settle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    write_labels(prompt / "labels.jsonl", [label("d1:a", "Levon", "good"), label("d1:a", "Hampus", "bad", ["too long"], "It reads like a lab report.")])
    write_labels(
        prompt / "cases" / "private" / "diary" / "labels.jsonl",
        [label("d1:private/diary/day1", "Levon", "bad"), label("d1:private/diary/day1", "Hampus", "good")],
    )
    monkeypatch.chdir(tmp_path)

    code = run(["disagreements", "daily"], make_model=unused_model)

    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        'd1:a  Levon: good  Hampus: bad (too long) "It reads like a lab report."',
        "d1:private/diary/day1  Levon: bad  Hampus: good",
        "2 cards to settle",
    ]


def test_nothing_to_settle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    write_labels(prompt / "labels.jsonl", [label("d1:a", "Levon", "good"), label("d1:a", "Hampus", "good")])
    monkeypatch.chdir(tmp_path)

    code = run(["disagreements", "daily"], make_model=unused_model)

    assert code == 0
    assert capsys.readouterr().out.splitlines() == ["nothing to settle"]


def test_settling_a_card_takes_it_off_the_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    source = prompt / "cases" / "private" / "diary" / "labels.jsonl"
    write_labels(source, [label("d1:private/diary/day1", "Levon", "good"), label("d1:private/diary/day1", "Hampus", "bad")])
    monkeypatch.chdir(tmp_path)

    code = run(["settle", "daily", "d1:private/diary/day1", "bad", "--grader", "Levon", "--note", "rule: never guess sleep"], make_model=unused_model)
    run(["disagreements", "daily"], make_model=unused_model)

    assert code == 0
    assert capsys.readouterr().out.splitlines()[-1] == "nothing to settle"
    settled = json.loads(source.read_text().splitlines()[-1])
    assert {k: settled[k] for k in ("card_id", "case_id", "grader", "verdict", "note", "settled")} == {
        "card_id": "d1:private/diary/day1",
        "case_id": "private/diary/day1",
        "grader": "Levon",
        "verdict": "bad",
        "note": "rule: never guess sleep",
        "settled": True,
    }
    assert not (prompt / "labels.jsonl").exists()


def test_settling_an_unknown_card_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_suite(tmp_path, {"a": "Rest today."})
    monkeypatch.chdir(tmp_path)

    code = run(["settle", "daily", "d9:a", "good", "--grader", "Levon"], make_model=unused_model)

    assert code == 2
    assert "no labels for card d9:a" in capsys.readouterr().err


def test_settling_needs_good_or_bad(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_suite(tmp_path, {"a": "Rest today."})
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exit:
        run(["settle", "daily", "d1:a", "skip", "--grader", "Levon"], make_model=unused_model)

    assert exit.value.code == 2
