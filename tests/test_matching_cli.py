import json
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import unused_model
from tests.test_agreement_cli import RUBRIC_TAIL, swipes
from tests.test_judges_cli import judging, make_judged_suite
from whetstone.entry.cli import run
from whetstone.features.matching.core import swipe_id

LONG = "Your HRV dipped and your sleep latency rose, so today is a recovery day. " * 4


def swiped(case: str, verdict: str = "bad", note: str = "Says HRV and sleep latency, nobody talks like that", reasons: list[str] | None = None, grader: str = "Hampus", output: Any = "Your HRV is low.", at: str = "2026-11-20T08:00:00+00:00") -> dict[str, Any]:
    return {"card_id": f"d:{case}", "deck_id": "d", "case_id": case, "input": {"text": case}, "output": output, "caught_by": [],
            "grader": grader, "verdict": verdict, "reasons": reasons or [], "note": note, "at": at}


def write_labels(file: Path, labels: list[dict[str, Any]]) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("".join(json.dumps(label) + "\n" for label in labels))


def read_lines(file: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in file.read_text().splitlines()] if file.is_file() else []


def test_notes_prints_each_unmatched_note_as_a_json_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    noted = swiped("c17", output=LONG)
    structured = swiped("c18", note="Too formal", reasons=["tone"], output={"line": "Rest."})
    write_labels(prompt / "labels.jsonl", [noted, structured, swiped("c19", note=""), swiped("c20", verdict="good", note="Nice")])
    monkeypatch.chdir(tmp_path)

    code = run(["notes", "daily"], make_model=unused_model)

    assert code == 0
    assert [json.loads(line) for line in capsys.readouterr().out.splitlines()] == [
        {"swipe": swipe_id(noted), "grader": "Hampus", "card": "d:c17", "note": "Says HRV and sleep latency, nobody talks like that", "reasons": [], "excerpt": LONG[:160] + "…"},
        {"swipe": swipe_id(structured), "grader": "Hampus", "card": "d:c18", "note": "Too formal", "reasons": ["tone"], "excerpt": '{"line": "Rest."}'},
    ]


def test_map_sure_counts_the_swipe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    noted = swiped("c17")
    write_labels(prompt / "labels.jsonl", [noted])
    monkeypatch.chdir(tmp_path)

    code = run(["map", "daily", swipe_id(noted), "--reasons", "banned", "--sure", "--why", "Quotes HRV, a banned term"], make_model=unused_model)

    assert code == 0
    assert capsys.readouterr().out.splitlines() == ["counted  d:c17 · Hampus · banned (sure)"]
    [event] = read_lines(prompt / "matches.jsonl")
    assert (event["event"], event["swipe"], event["reasons"], event["why"]) == ("proposed", swipe_id(noted), ["banned"], "Quotes HRV, a banned term")
    [_, line] = read_lines(prompt / "labels.jsonl")
    assert (line["reasons"], line["verdict"], line["matched_by"], line["swipe"]) == (["banned"], "bad", "claude", swipe_id(noted))
    run(["notes", "daily"], make_model=unused_model)
    assert capsys.readouterr().out == ""


def test_a_sure_match_measures_an_unmeasured_judge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."}, 'reasons = ["assumes the outcome"]\n' + RUBRIC_TAIL)
    noted = swiped("n", note="It assumes I skipped the run", output="Did you skip it?", grader="Levon")
    write_labels(prompt / "labels.jsonl", swipes(good_failed=0)[:14] + [noted])  # 10 good, 4 bad tapped, 1 note
    monkeypatch.chdir(tmp_path)
    judge = lambda _workspace: judging("yes")  # noqa: E731
    run(["agreement", "daily"], make_model=unused_model, make_judge=judge)
    assert "assumes: unmeasured" in capsys.readouterr().out.splitlines()

    run(["map", "daily", swipe_id(noted), "--reasons", "assumes the outcome", "--sure", "--why", "Says it assumes"], make_model=unused_model)
    code = run(["agreement", "daily"], make_model=unused_model, make_judge=judge)

    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert out[:4] == [
        "counted  d:n · Levon · assumes the outcome (sure)",
        "15 judge calls",
        "judge     bad swipes   tapped   claude sure   good / bad    gate",
        "assumes            5        4             1   100% / 100%   trusted",
    ]
    assert "assumes: trusted" in out
    assert read_lines(prompt / "labels.jsonl")[-1]["verdict"] == "bad"
