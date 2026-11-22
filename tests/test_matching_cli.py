import json
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeModel, unused_model
from tests.test_agreement_cli import RUBRIC_TAIL, swipes
from tests.test_judges_cli import judging, make_judged_suite
from starlette.testclient import TestClient

from tests.test_server import AUTH, TOKEN
import whetstone.entry.cli as cli
from whetstone.entry.cli import run
from whetstone.entry.server import make_app
from whetstone.features.workspace.load import load_prompt
from whetstone.features.grading.store import add_label, load_labels
from whetstone.features.matching.core import Refusal, answer, case_of, swipe_id
from whetstone.features.matching.store import add_event, load_events
from whetstone.platform import jsonl

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

    def judge(_workspace: Path) -> FakeModel:
        return judging("yes")

    run(["agreement", "daily"], make_model=unused_model, make_judge=judge)
    assert "assumes: unmeasured" in capsys.readouterr().out.splitlines()

    run(["map", "daily", swipe_id(noted), "--reasons", "assumes the outcome", "--sure", "--why", "Says it assumes"], make_model=unused_model)
    code = run(["agreement", "daily"], make_model=unused_model, make_judge=judge)

    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert out[:4] == [
        "counted  d:n · Levon · assumes the outcome (sure)",
        "15 judge calls",
        "judge     bad swipes   tapped   claude sure   confirmed   undone   good / bad    gate",
        "assumes            5        4             1           0        0   100% / 100%   trusted",
    ]
    assert "assumes: trusted" in out
    assert read_lines(prompt / "labels.jsonl")[-1]["verdict"] == "bad"


def test_agreement_table_shows_a_dash_for_a_side_nobody_swiped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."}, 'reasons = ["assumes the outcome"]\n' + RUBRIC_TAIL)
    write_labels(prompt / "labels.jsonl", swipes(good_failed=0)[10:])  # 5 bad, no good
    monkeypatch.chdir(tmp_path)

    code = run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: judging("yes"))

    assert code == 1
    assert capsys.readouterr().out.splitlines()[2] == "assumes            5        5             0           0        0   — / 100%      untrusted"


def test_one_note_counts_for_two_judges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."}, 'reasons = ["assumes the outcome"]\n' + RUBRIC_TAIL)
    (prompt / "checks" / "jargon.judge.toml").write_text('reasons = ["biometric jargon"]\n' + RUBRIC_TAIL)
    noted = swiped("n", note="Assumes I skipped, and says HRV", output="Did you skip it?")
    write_labels(prompt / "labels.jsonl", [noted])
    monkeypatch.chdir(tmp_path)

    run(["map", "daily", swipe_id(noted), "--reasons", "assumes the outcome", "biometric jargon", "--sure", "--why", "Names both"], make_model=unused_model)
    run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: judging("yes"))

    out = capsys.readouterr().out.splitlines()
    assert out[0] == "counted  d:n · Hampus · assumes the outcome, biometric jargon (sure)"
    assert sorted(out[3:5]) == [
        "assumes            1        0             1           0        0   — / 100%      untrusted",
        "jargon             1        0             1           0        0   — / 100%      untrusted",
    ]


@pytest.mark.parametrize(
    ("swipe", "reasons", "refusal"),
    [
        ("replaced", ["banned"], "Hampus swiped d:c2 again, matching the new note instead"),
        ("noted", ["banned", "vague"], 'no check stands for "vague"'),
        ("matched", ["banned"], "already matched"),
        ("s_000000000000", ["banned"], "no swipe s_000000000000"),
    ],
)
def test_map_refuses_and_writes_nothing(swipe: str, reasons: list[str], refusal: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    lines = {"noted": swiped("c1"), "replaced": swiped("c2"), "matched": swiped("c3")}
    write_labels(prompt / "labels.jsonl", [*lines.values(), swiped("c2", note="It's too long", at="2026-11-20T09:00:00+00:00")])
    monkeypatch.chdir(tmp_path)
    run(["map", "daily", swipe_id(lines["matched"]), "--reasons", "banned", "--sure", "--why", "Quotes HRV"], make_model=unused_model)
    capsys.readouterr()
    before = ((prompt / "labels.jsonl").read_text(), (prompt / "matches.jsonl").read_text())
    swipe = swipe_id(lines[swipe]) if swipe in lines else swipe

    code = run(["map", "daily", swipe, "--reasons", *reasons, "--sure", "--why", "Quotes HRV"], make_model=unused_model)

    assert code == 1
    assert capsys.readouterr().out.splitlines() == [f"refused  {swipe} · {refusal}"]
    assert ((prompt / "labels.jsonl").read_text(), (prompt / "matches.jsonl").read_text()) == before


def test_a_real_data_match_stays_in_its_private_source_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    private = prompt / "cases" / "private" / "diary"
    noted = swiped("private/diary/day1")
    write_labels(private / "labels.jsonl", [noted])
    monkeypatch.chdir(tmp_path)

    run(["map", "daily", swipe_id(noted), "--reasons", "banned", "--sure", "--why", "Quotes HRV"], make_model=unused_model)
    run(["notes", "daily"], make_model=unused_model)

    assert capsys.readouterr().out.splitlines() == ["counted  d:private/diary/day1 · Hampus · banned (sure)"]
    assert [event["swipe"] for event in read_lines(private / "matches.jsonl")] == [swipe_id(noted)]
    assert len(read_lines(private / "labels.jsonl")) == 2
    assert not (prompt / "matches.jsonl").exists() and not (prompt / "labels.jsonl").exists()


def test_agreement_table_says_how_far_an_unmeasured_judge_is(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."}, 'reasons = ["assumes the outcome"]\n' + RUBRIC_TAIL)
    write_labels(prompt / "labels.jsonl", swipes(good_failed=0)[:12])  # 10 good, 2 bad
    monkeypatch.chdir(tmp_path)

    run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: judging("yes"))

    assert capsys.readouterr().out.splitlines()[1:3] == [
        "judge     bad swipes   tapped   claude sure   confirmed   undone   good / bad    gate",
        "assumes            2        2             0           0        0   —             unmeasured · 2 of 5 bad",
    ]


def test_a_reswipe_written_while_map_ran_wins_over_the_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."}, 'reasons = ["assumes the outcome"]\n' + RUBRIC_TAIL)
    noted = swiped("n", note="It assumes I skipped the run", output="Did you skip it?", grader="Levon")
    write_labels(prompt / "labels.jsonl", swipes(good_failed=0)[:14] + [noted])
    monkeypatch.chdir(tmp_path)
    run(["map", "daily", swipe_id(noted), "--reasons", "assumes the outcome", "--sure", "--why", "Says it assumes"], make_model=unused_model)
    # The server stamped this re-swipe before map stamped its line, but appended it after map had checked.
    with (prompt / "labels.jsonl").open("a") as f:
        f.write(json.dumps(swiped("n", verdict="good", note="", output="Did you skip it?", grader="Levon", at="2026-11-20T08:30:00+00:00")) + "\n")

    run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: judging("yes"))

    out = capsys.readouterr().out.splitlines()
    assert "  Levon: good 10/11 (91%), bad 4/4 (100%)" in out
    assert out[3].startswith("assumes            4        4             0")


def test_map_ask_waits_for_the_grader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    noted = swiped("c17")
    write_labels(prompt / "labels.jsonl", [noted])
    monkeypatch.chdir(tmp_path)

    code = run(["map", "daily", swipe_id(noted), "--reasons", "banned", "--ask", "--why", "Might mean the banned words"], make_model=unused_model)
    run(["notes", "daily"], make_model=unused_model)

    assert code == 0
    match = "m_" + swipe_id(noted).removeprefix("s_")
    assert capsys.readouterr().out.splitlines() == [f"waiting  d:c17 · Hampus · banned (ask {match})"]
    assert [(e["event"], e["kind"]) for e in read_lines(prompt / "matches.jsonl")] == [("proposed", "ask")]
    assert read_lines(prompt / "labels.jsonl") == [noted]


def test_map_needs_sure_or_ask(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_judged_suite(tmp_path, {"a": "Rest today."})
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as stopped:
        run(["map", "daily", "s_1", "--reasons", "banned", "--why", "x"], make_model=unused_model)

    assert stopped.value.code == 2


def answered_in_app(prompt: Path, match: str, choice: str, grader: str = "Hampus", reason: str | None = None, covered: frozenset[str] = frozenset({"banned", "assumes", "assumes the outcome"})) -> None:
    """The grader's answer, written as the swipe server writes it."""
    labels, events = load_labels(prompt), load_events(prompt)
    writes = answer(labels, events, set(covered), grader, match, choice, reason, "2026-11-21T10:00:00+00:00")
    assert writes is not None and not isinstance(writes, Refusal)
    event, line = writes
    if line is not None:
        add_label(prompt, line)
    if event is not None:
        add_event(prompt, case_of(labels, events, event), event)


def test_a_yes_counts_under_confirmed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."}, 'reasons = ["assumes the outcome"]\n' + RUBRIC_TAIL)
    noted = swiped("n", note="Feels like it guessed what I did", output="Did you skip it?", grader="Levon")
    write_labels(prompt / "labels.jsonl", swipes(good_failed=0)[:14] + [noted])
    monkeypatch.chdir(tmp_path)
    run(["map", "daily", swipe_id(noted), "--reasons", "assumes the outcome", "--ask", "--why", "Guessing is assuming"], make_model=unused_model)

    answered_in_app(prompt, "m_" + swipe_id(noted).removeprefix("s_"), "yes", grader="Levon")
    run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: judging("yes"))

    out = capsys.readouterr().out.splitlines()
    assert out[2:4] == [
        "judge     bad swipes   tapped   claude sure   confirmed   undone   good / bad    gate",
        "assumes            5        4             0           1        0   100% / 100%   trusted",
    ]
    assert read_lines(prompt / "labels.jsonl")[-1]["verdict"] == "bad"


def test_agreement_says_what_was_kept_and_what_waits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    kept, waiting, other = swiped("c1", note="Feels off"), swiped("c2", note="Too clinical"), swiped("c3", note="Nah", grader="Levon")
    write_labels(prompt / "labels.jsonl", [kept, waiting, other])
    monkeypatch.chdir(tmp_path)
    for label in (kept, waiting, other):
        run(["map", "daily", swipe_id(label), "--reasons", "banned", "--ask", "--why", "Maybe"], make_model=unused_model)
    answered_in_app(prompt, "m_" + swipe_id(kept).removeprefix("s_"), "no")
    capsys.readouterr()

    run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: judging("yes"))

    assert capsys.readouterr().out.splitlines()[3] == "1 note kept as an idea for a new check · 1 waiting on Hampus · 1 waiting on Levon"


def test_deleting_the_judge_lists_an_asked_note_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    noted = swiped("c17", note="It guessed what I did")
    write_labels(prompt / "labels.jsonl", [noted])
    monkeypatch.chdir(tmp_path)
    run(["map", "daily", swipe_id(noted), "--reasons", "assumes", "--ask", "--why", "Guessing is assuming"], make_model=unused_model)
    (prompt / "checks" / "assumes.judge.toml").unlink()
    capsys.readouterr()

    run(["notes", "daily"], make_model=unused_model)

    assert [json.loads(line)["swipe"] for line in capsys.readouterr().out.splitlines()] == [swipe_id(noted)]


def test_agreement_counts_an_undone_match_until_redone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."}, 'reasons = ["assumes the outcome"]\n' + RUBRIC_TAIL)
    noted = swiped("n", note="It assumes I skipped the run", output="Did you skip it?", grader="Levon")
    write_labels(prompt / "labels.jsonl", swipes(good_failed=0)[:14] + [noted])
    monkeypatch.chdir(tmp_path)
    run(["map", "daily", swipe_id(noted), "--reasons", "assumes the outcome", "--sure", "--why", "Says it assumes"], make_model=unused_model)
    phone = TestClient(make_app(load_prompt(tmp_path, "daily"), TOKEN))
    levon = {**AUTH, "X-Grader": "Levon"}
    match = "m_" + swipe_id(noted).removeprefix("s_")

    def table() -> list[str]:
        capsys.readouterr()
        run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: judging("yes"))
        return capsys.readouterr().out.splitlines()[1:3]

    assert phone.post(f"/api/matches/{match}", headers=levon, json={"answer": "undo"}).status_code == 200
    assert table() == [
        "judge     bad swipes   tapped   claude sure   confirmed   undone   good / bad    gate",
        "assumes            4        4             0           0        1   —             unmeasured · 4 of 5 bad",
    ]
    assert phone.post(f"/api/matches/{match}", headers=levon, json={"answer": "redo"}).status_code == 200
    assert table()[1] == "assumes            5        4             1           0        0   100% / 100%   trusted"


def test_settling_a_card_claude_matched_is_a_call_not_a_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    noted = swiped("c17")
    write_labels(prompt / "labels.jsonl", [noted])
    monkeypatch.chdir(tmp_path)
    run(["map", "daily", swipe_id(noted), "--reasons", "banned", "--sure", "--why", "Quotes HRV, a banned term"], make_model=unused_model)

    run(["settle", "daily", "d:c17", "good", "--grader", "Levon"], make_model=unused_model)
    code = run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: judging("yes"))

    assert code in (0, 1)
    settled = read_lines(prompt / "labels.jsonl")[-1]
    assert (settled["grader"], settled["verdict"], settled["settled"]) == ("Levon", "good", True)
    assert "matched_by" not in settled and "swipe" not in settled


def test_a_check_that_fails_to_load_stops_agreement_before_any_judge_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    write_labels(prompt / "labels.jsonl", [swiped("c17")])
    (prompt / "checks" / "half_written.py").write_text("REASONS = [\n")
    monkeypatch.chdir(tmp_path)
    judge = judging("yes")

    code = run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: judge)

    assert code != 0
    assert judge.requests == []


def test_a_match_written_after_a_reswipe_does_not_bring_back_the_old_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    old = swiped("c17")
    # map read the labels just before Hampus swiped again, and wrote its line just after
    late_match = {**old, "reasons": ["banned"], "matched_by": "claude", "swipe": swipe_id(old), "match": "m_1", "counted": "sure", "at": "2026-11-20T09:00:01+00:00"}
    write_labels(prompt / "labels.jsonl", [old, swiped("c17", grader="Levon", note=""), swiped("c17", verdict="good", note="", at="2026-11-20T09:00:00+00:00"), late_match])
    monkeypatch.chdir(tmp_path)

    run(["disagreements", "daily"], make_model=unused_model)

    assert capsys.readouterr().out.splitlines() == ["d:c17  Hampus: good  Levon: bad", "1 card to settle"]


def test_a_judge_deleted_while_agreement_judges_still_gets_its_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."}, 'reasons = ["assumes the outcome"]\n' + RUBRIC_TAIL)
    jargon = prompt / "checks" / "jargon.judge.toml"
    jargon.write_text('reasons = ["biometric jargon"]\n' + RUBRIC_TAIL)
    write_labels(prompt / "labels.jsonl", [swiped("c17")])
    monkeypatch.chdir(tmp_path)

    def answer(_request: dict[str, Any]) -> str:
        jargon.unlink(missing_ok=True)  # the session runner deletes it while the judge calls run
        return json.dumps({"answer": "no"})

    code = run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: FakeModel(answer))

    assert code in (0, 1)
    assert [line.split()[0] for line in capsys.readouterr().out.splitlines()[1:4]] == ["judge", "assumes", "jargon"]


def mapped_between_reads(monkeypatch: pytest.MonkeyPatch, prompt: Path) -> None:
    """Right after the first read of the labels file, a grader swipes and `map` asks about it, as the server and Claude
    do while a command runs."""
    read = jsonl.read
    late = swiped("c99", note="Swiped while the command ran", at="2026-11-20T10:00:00+00:00")
    pending = [late]

    def racing(path: Path) -> list[dict[str, Any]]:
        records = read(path)
        if path.name == "labels.jsonl" and pending:
            jsonl.append(prompt / "labels.jsonl", pending.pop())
            jsonl.append(prompt / "matches.jsonl", {"event": "proposed", "id": "m_" + swipe_id(late).removeprefix("s_"), "swipe": swipe_id(late), "grader": "Hampus", "card_id": "d:c99", "kind": "ask", "reasons": ["banned"], "why": "Maybe", "at": late["at"]})
        return records

    monkeypatch.setattr(jsonl, "read", racing)


def test_a_swipe_mapped_while_agreement_judges_does_not_crash_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    write_labels(prompt / "labels.jsonl", [swiped("c17")])
    monkeypatch.chdir(tmp_path)
    mapped_between_reads(monkeypatch, prompt)

    code = run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: judging("yes"))

    assert code in (0, 1)
    assert capsys.readouterr().out.splitlines()[1].startswith("judge ")


@pytest.mark.parametrize("command", ["notes", "reasons"])
def test_a_swipe_mapped_between_reads_does_not_crash_notes_or_reasons(command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    write_labels(prompt / "labels.jsonl", [swiped("c17")])
    monkeypatch.chdir(tmp_path)
    mapped_between_reads(monkeypatch, prompt)

    assert run([command, "daily"], make_model=unused_model) == 0


def test_a_sure_match_whose_proposal_a_crash_lost_never_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."}, 'reasons = ["assumes the outcome"]\n' + RUBRIC_TAIL)
    noted = swiped("n", note="It assumes I skipped the run", output="Did you skip it?", grader="Levon")
    write_labels(prompt / "labels.jsonl", swipes(good_failed=0)[:14] + [noted])
    monkeypatch.chdir(tmp_path)

    def died(*_args: object) -> None:
        raise OSError("killed")

    with monkeypatch.context() as crash:
        crash.setattr(cli, "add_event", died)
        with pytest.raises(OSError):
            run(["map", "daily", swipe_id(noted), "--reasons", "assumes the outcome", "--sure", "--why", "Says it assumes"], make_model=unused_model)
    orphan = read_lines(prompt / "labels.jsonl")[-1]["match"]
    capsys.readouterr()

    run(["map", "daily", swipe_id(noted), "--reasons", "assumes the outcome", "--ask", "--why", "Maybe assuming"], make_model=unused_model)
    [asked] = read_lines(prompt / "matches.jsonl")
    answered_in_app(prompt, asked["id"], "no", grader="Levon")
    run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: judging("yes"))

    assert asked["id"] != orphan
    assert capsys.readouterr().out.splitlines()[3].startswith("assumes            4        4             0           0        0")


def test_a_sure_match_matched_again_since_stops_counting_when_its_check_comes_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."}, 'reasons = ["assumes the outcome"]\n' + RUBRIC_TAIL)
    assumes = prompt / "checks" / "assumes.judge.toml"
    (prompt / "checks" / "jargon.judge.toml").write_text('reasons = ["biometric jargon"]\n' + RUBRIC_TAIL)
    noted = swiped("n", note="Assumes I skipped, and says HRV", output="Did you skip it?")
    write_labels(prompt / "labels.jsonl", [noted])
    monkeypatch.chdir(tmp_path)
    run(["map", "daily", swipe_id(noted), "--reasons", "assumes the outcome", "--sure", "--why", "Says it assumes"], make_model=unused_model)
    rubric = assumes.read_text()
    assumes.unlink()  # the judge deleted, so the sure match went stale
    run(["map", "daily", swipe_id(noted), "--reasons", "biometric jargon", "--ask", "--why", "Says HRV"], make_model=unused_model)
    assumes.write_text(rubric)  # and brought back
    capsys.readouterr()

    run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: judging("yes"))

    rows = {line.split()[0]: line for line in capsys.readouterr().out.splitlines()[2:4]}
    assert rows["assumes"].startswith("assumes            0        0             0           0        0")
