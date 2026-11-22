from pathlib import Path

import pytest

from tests.fakes import unused_model
from tests.test_judges_cli import make_judged_suite
from tests.test_matching_cli import answered_in_app, swiped, write_labels
from whetstone.entry.cli import run
from whetstone.features.grading.store import load_labels
from whetstone.features.matching.core import kept_and_waiting, swipe_id
from whetstone.features.matching.store import load_events


def test_a_note_answered_no_can_be_matched_to_a_new_judge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    noted = swiped("c17", note="It guessed what I did")
    write_labels(prompt / "labels.jsonl", [noted])
    monkeypatch.chdir(tmp_path)
    run(["map", "daily", swipe_id(noted), "--reasons", "banned", "--ask", "--why", "Maybe"], make_model=unused_model)
    answered_in_app(prompt, "m_" + swipe_id(noted).removeprefix("s_"), "no")
    capsys.readouterr()

    refused = run(["map", "daily", swipe_id(noted), "--reasons", "banned", "assumes", "--sure", "--why", "Again"], make_model=unused_model)
    counted = run(["map", "daily", swipe_id(noted), "--reasons", "assumes", "--sure", "--why", "Guessing is assuming"], make_model=unused_model)
    run(["reasons", "daily"], make_model=unused_model)

    assert (refused, counted) == (1, 0)
    assert capsys.readouterr().out.splitlines() == [
        f'refused  {swipe_id(noted)} · Hampus answered No to "banned"',
        "counted  d:c17 · Hampus · assumes (sure)",
        "every reason has a check",
    ]
    assert kept_and_waiting(load_labels(prompt), load_events(prompt), {"banned", "assumes"}) == (0, {})


def test_reasons_names_the_swipe_of_a_note_answered_no(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    noted, fresh = swiped("c17", note="It guessed what I did"), swiped("c18", note="Too clinical")
    write_labels(prompt / "labels.jsonl", [noted, fresh])
    monkeypatch.chdir(tmp_path)
    run(["map", "daily", swipe_id(noted), "--reasons", "banned", "--ask", "--why", "Maybe"], make_model=unused_model)
    answered_in_app(prompt, "m_" + swipe_id(noted).removeprefix("s_"), "no")
    capsys.readouterr()

    run(["reasons", "daily"], make_model=unused_model)

    assert capsys.readouterr().out.splitlines() == [f'1  note: "It guessed what I did" · {swipe_id(noted)}', '1  note: "Too clinical"']
