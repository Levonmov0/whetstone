import json
from pathlib import Path

import pytest

from tests.fakes import FakeModel, unused_model
from tests.test_check_cli import make_suite
from tests.test_judges_cli import JUDGE_SETTINGS, add_private_case, judging, make_judged_suite
from whetstone.entry.cli import run


def swiped(card: str, output: str, verdict: str, reasons: list[str] | None = None, grader: str = "Levon") -> dict[str, object]:
    return {"card_id": card, "deck_id": "d", "case_id": card, "input": {"text": card}, "output": output, "caught_by": [],
            "grader": grader, "verdict": verdict, "reasons": reasons or [], "note": "", "at": "2026-10-26T08:00:00+00:00"}


def write_labels(file: Path, labels: list[dict[str, object]]) -> None:
    file.write_text("".join(json.dumps(label) + "\n" for label in labels))


def swipes(good_failed: int) -> list[dict[str, object]]:
    """10 good swipes, of which the judge fails `good_failed`, and 5 bad ones for its rule, all of which it fails."""
    good = [swiped(f"g{i}", "Why did you skip it?" if i < good_failed else "Rest today.", "good") for i in range(10)]
    return good + [swiped(f"b{i}", "Did you skip it?", "bad", ["assumes the outcome"]) for i in range(5)]


def test_agreement_shows_a_trusted_judge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."}, 'reasons = ["assumes the outcome"]\n' + RUBRIC_TAIL)
    write_labels(prompt / "labels.jsonl", swipes(good_failed=1) + [swiped("g5", "Rest today.", "good", grader="Hampus")])
    judge = judging("yes")
    monkeypatch.chdir(tmp_path)

    code = run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: judge)

    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert out[out.index("assumes: trusted") + 1] == "  Levon: good 9/10 (90%), bad 5/5 (100%)"
    assert len(judge.requests) == 15  # each swiped card once, however many graders swiped it
    assert any('{"text": "b0"}' in request["input"] and '"Did you skip it?"' in request["input"] for request in judge.requests)


def test_agreement_explains_an_untrusted_judge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."}, 'reasons = ["assumes the outcome"]\n' + RUBRIC_TAIL)
    write_labels(prompt / "labels.jsonl", swipes(good_failed=3))
    monkeypatch.chdir(tmp_path)

    code = run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: judging("yes"))

    out = capsys.readouterr().out.splitlines()
    assert code == 1
    assert "assumes: untrusted" in out
    assert "  fails outputs Levon called good (70%); sharpen the rubric" in out


def test_agreement_names_a_judge_never_shown_its_rule_broken(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."}, 'reasons = ["assumes the outcome"]\n' + RUBRIC_TAIL)
    write_labels(prompt / "labels.jsonl", swipes(good_failed=0)[:12])  # 10 good, only 2 bad
    monkeypatch.chdir(tmp_path)

    code = run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: judging("yes"))

    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert out[out.index("assumes: unmeasured"):] == [
        "assumes: unmeasured",
        "  Levon: good 10/10 (100%), bad 2/2 (100%)",
        "  only 2 bad swipes for this rule, so it guards the run untested; swipe at least 3 more to measure it",
    ]


def test_agreement_without_judges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_suite(tmp_path, {"a": "Rest today."})
    monkeypatch.chdir(tmp_path)

    code = run(["agreement", "daily"], make_model=unused_model, make_judge=unused_model)

    assert code == 0
    assert capsys.readouterr().out.splitlines() == ["no judges in checks/"]


def test_agreement_keeps_real_data_from_an_unused_judge_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    add_private_case(prompt)
    write_labels(prompt / "cases" / "private" / "diary" / "labels.jsonl", [swiped("private/diary/day1", "Rest.", "good")])
    (tmp_path / "whetstone.toml").write_text('repo_providers = ["anthropic"]\n' + JUDGE_SETTINGS)
    judge = judging("no")
    monkeypatch.chdir(tmp_path)

    code = run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: judge)

    assert code == 2
    assert "real-data cases go only to providers this repo already uses (anthropic); openai is not one" in capsys.readouterr().err
    assert judge.requests == []


RUBRIC_TAIL = '''question = "Does the line assume whether the athlete did what the coach advised?"
pass = "no"
[fail]
yes = "assumes whether they did the coach's advice"
'''


def test_agreement_prints_its_call_count_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."}, 'reasons = ["assumes the outcome"]\n' + RUBRIC_TAIL)
    write_labels(prompt / "labels.jsonl", swipes(good_failed=1))
    printed_before: list[str] = []

    def answer(request: dict[str, object]) -> object:
        if not printed_before:
            printed_before.append(capsys.readouterr().out)
        return judging("yes").answer(request)

    monkeypatch.chdir(tmp_path)

    run(["agreement", "daily"], make_model=unused_model, make_judge=lambda _workspace: FakeModel(answer))

    assert printed_before == ["15 judge calls\n"]
