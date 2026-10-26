"""Pure rules for a check run: how results are reported and what exit code they give."""

from dataclasses import dataclass
import json
from typing import Any


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


def judge_failures(rubric: Rubric, reply: str) -> list[str]:
    """The judge's reply as a check result: no messages when it gave the passing answer, else that answer's reason."""
    answer = json.loads(reply)["answer"]
    return [] if answer == rubric.passing else [rubric.fail[answer]]
