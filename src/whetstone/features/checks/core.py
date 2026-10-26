"""Pure rules for a check run: how results are reported and what exit code they give."""

from dataclasses import dataclass
import json
from typing import Any, cast


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    failures: dict[str, list[str]]  # check name -> its failure messages, empty when it passed


def report(results: list[CaseResult], check_names: list[str]) -> tuple[list[str], int]:
    """The lines to print, and the exit code: 0 when every case passes every check, else 1."""
    lines: list[str] = []
    for r in results:
        failed = {name: msgs for name, msgs in r.failures.items() if msgs}
        if not failed:
            lines.append(f"PASS {r.case_id}")
        for name, msgs in failed.items():
            lines += [f"FAIL {r.case_id}: {name}: {m}" for m in msgs]
    lines.append("")
    for name in check_names:
        passed = sum(1 for r in results if not r.failures[name])
        lines.append(f"{name}: {passed}/{len(results)}")
    clean = sum(1 for r in results if not any(r.failures.values()))
    lines.append(f"{clean} of {len(results)} cases pass every check")
    return lines, 0 if clean == len(results) else 1


def uncovered_reasons(labels: list[dict[str, Any]], covered: set[str]) -> list[tuple[str, int]]:
    """Left-swipe reasons, and notes without one, that no check stands for yet: how often each came up, in first-seen order."""
    counts: dict[str, int] = {}
    for label in labels:
        if label["verdict"] != "bad":
            continue
        for reason in label["reasons"] or [f'note: "{label["note"]}"']:
            if reason not in covered:
                counts[reason] = counts.get(reason, 0) + 1
    return list(counts.items())


@dataclass(frozen=True)
class Rubric:
    """A judge: one question about one rule, one passing answer, and failing answers each mapped to its reason."""

    question: str
    guide: str
    passing: str
    fail: dict[str, str]
    reasons: list[str]  # swipe reasons this judge stands for, besides its failing answers


def covered_reasons(code_checks: list[str], judges: dict[str, Rubric]) -> set[str]:
    """The swipe reasons some check already stands for: its name, or one of a judge's failing answers or reasons."""
    covered = set(code_checks) | set(judges)
    for rubric in judges.values():
        covered |= set(rubric.fail.values()) | set(rubric.reasons)
    return covered


JUDGE_INSTRUCTIONS = "You check one output of a prompt against one rule. Answer the question about the output, using the input only as context."


def judge_request(rubric: Rubric, model: str, case_input: Any, output: Any) -> dict[str, Any]:
    """The judge's request body, for the OpenAI Responses API."""
    text = f"Question: {rubric.question}\n\n{rubric.guide}\n\nInput:\n{json.dumps(case_input, ensure_ascii=False)}\n\nOutput:\n{json.dumps(output, ensure_ascii=False)}"
    # A strict schema whose answer is one of the rubric's choices: the model can't reply with anything else.
    answers = {"type": "string", "enum": [rubric.passing, *rubric.fail]}
    schema = {"type": "object", "properties": {"answer": answers}, "required": ["answer"], "additionalProperties": False}
    return {"model": model, "instructions": JUDGE_INSTRUCTIONS, "input": text, "text": {"format": {"type": "json_schema", "name": "verdict", "strict": True, "schema": schema}}}


class JudgeAnswerError(Exception):
    """A judge reply that isn't one of the rubric's answers. Its message is the reply, or the answer in it."""


def judge_failures(rubric: Rubric, reply: str) -> list[str]:
    """The judge's reply as a check result: no messages when it gave the passing answer, else that answer's reason."""
    try:
        parsed = json.loads(reply)
    except ValueError:
        raise JudgeAnswerError(reply) from None
    answer = cast(dict[str, Any], parsed).get("answer") if isinstance(parsed, dict) else None
    if answer == rubric.passing:
        return []
    if not isinstance(answer, str) or answer not in rubric.fail:
        raise JudgeAnswerError(answer if isinstance(answer, str) else reply)
    return [rubric.fail[answer]]


@dataclass(frozen=True)
class Side:
    agreed: int
    total: int


@dataclass(frozen=True)
class Agreement:
    good: Side  # cards the grader called good, and how many of them the judge passed
    bad: Side  # cards the grader called bad for this judge's rule, and how many of them the judge failed


def agreement(labels: list[dict[str, Any]], verdicts: dict[str, bool], rule: set[str]) -> dict[str, Agreement]:
    """Per grader, how often the judge agreed with their latest swipe on each card. `verdicts` holds whether the judge
    passed each card; `rule` is every reason that means this judge's rule. A bad swipe for another reason, or a skip,
    says nothing about this judge and isn't counted. A settled call is just that grader's latest swipe."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for label in sorted(labels, key=lambda label: str(label.get("at", ""))):
        latest[label["grader"], label["card_id"]] = label
    rows: dict[str, list[int]] = {}
    for (grader, card), label in latest.items():
        row = rows.setdefault(grader, [0, 0, 0, 0])
        if label["verdict"] == "good":
            row[0] += verdicts[card]
            row[1] += 1
        elif label["verdict"] == "bad" and rule & set(label["reasons"]):
            row[2] += not verdicts[card]
            row[3] += 1
    return {grader: Agreement(Side(row[0], row[1]), Side(row[2], row[3])) for grader, row in rows.items()}
