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
    """Left-swipe reasons, and notes without one, that no check stands for yet, with how often each came up: most
    frequent first, ties in first-seen order. A bad swipe with neither says nothing a check could stand for."""
    counts: dict[str, int] = {}
    for label in labels:
        if label["verdict"] != "bad":
            continue
        for reason in label["reasons"] or ([f'note: "{label["note"]}"'] if label["note"] else []):
            if reason not in covered:
                counts[reason] = counts.get(reason, 0) + 1
    return sorted(counts.items(), key=lambda item: -item[1])


@dataclass(frozen=True)
class Rubric:
    """A judge: one question about one rule, one passing answer, and failing answers each mapped to its reason."""

    question: str
    guide: str
    passing: str
    fail: dict[str, str]
    reasons: list[str]  # swipe reasons this judge stands for, besides its failing answers


def covered_reasons(code_checks: dict[str, list[str]], judges: dict[str, Rubric]) -> set[str]:
    """The swipe reasons some check already stands for: its name, a code check's declared reasons, or one of a judge's
    failing answers or reasons."""
    covered = set(code_checks) | set(judges) | {reason for reasons in code_checks.values() for reason in reasons}
    for rubric in judges.values():
        covered |= set(rubric.fail.values()) | set(rubric.reasons)
    return covered


JUDGE_INSTRUCTIONS = "You check one output of a prompt against one rule. Answer the question about the output, using the input only as context."


CLEF_PASSING = "the output is fine on this rule"


def judge_request(rubric: Rubric, provider: str, model: str, case_input: Any, output: Any) -> dict[str, Any]:
    """The judge's request body: for the OpenAI Responses API, or for Clef on Cloudflare Workers AI."""
    if provider == "cloudflare":
        # One choice question whose options are the rubric's answers: Clef scores only those, so it can't reply with
        # anything else. The output comes first, so a state Clef truncates to fit its window loses input, never output.
        question = f"{JUDGE_INSTRUCTIONS}\n\nQuestion: {rubric.question}\n\n{rubric.guide}"
        # Every option described alike: Clef leans toward the one option that has a description.
        criteria = {rubric.passing: CLEF_PASSING, **rubric.fail}
        state = {"output": output, "input": case_input}
        return {"model": model, "state": state, "questions": {"verdict": {"type": "choice", "instructions": question, "criteria": criteria}}}
    text = f"Question: {rubric.question}\n\n{rubric.guide}\n\nInput:\n{json.dumps(case_input, ensure_ascii=False)}\n\nOutput:\n{json.dumps(output, ensure_ascii=False)}"
    # A strict schema whose answer is one of the rubric's choices: the model can't reply with anything else.
    answers = {"type": "string", "enum": [rubric.passing, *rubric.fail]}
    schema = {"type": "object", "properties": {"answer": answers}, "required": ["answer"], "additionalProperties": False}
    return {"model": model, "instructions": JUDGE_INSTRUCTIONS, "input": text, "text": {"format": {"type": "json_schema", "name": "verdict", "strict": True, "schema": schema}}}


class JudgeAnswerError(Exception):
    """A judge reply that isn't one of the rubric's answers. Its message is the reply, or the answer in it."""


def judge_failures(rubric: Rubric, provider: str, reply: Any) -> list[str]:
    """The judge's reply as a check result: no messages when it gave the passing answer, else that answer's reason.
    An OpenAI reply is JSON text; a Clef reply is its result, with the choice under the question's id."""
    answer = _clef_choice(reply) if provider == "cloudflare" else _openai_answer(reply)
    if answer == rubric.passing:
        return []
    if not isinstance(answer, str) or answer not in rubric.fail:
        raise JudgeAnswerError(answer if isinstance(answer, str) else reply if isinstance(reply, str) else json.dumps(reply))
    return [rubric.fail[answer]]


def _openai_answer(reply: Any) -> Any:
    try:
        parsed = json.loads(reply)
    except (TypeError, ValueError):
        raise JudgeAnswerError(str(reply)) from None
    return cast(dict[str, Any], parsed).get("answer") if isinstance(parsed, dict) else None


def _clef_choice(reply: Any) -> Any:
    answers = cast(dict[str, Any], reply).get("answers") if isinstance(reply, dict) else None
    verdict = cast(dict[str, Any], answers).get("verdict") if isinstance(answers, dict) else None
    return cast(dict[str, Any], verdict).get("choice") if isinstance(verdict, dict) else None


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


TRUSTED, WARNED = 90, 80  # percent agreement on each side
MINIMUM = 5  # swipes a side needs from some grader before its percentage means anything


def judge_gate(agreements: dict[str, Agreement]) -> tuple[str, list[str]]:
    """Whether a judge can be optimized against: "trusted", "warn", "unmeasured" or "untrusted", with advice for each
    shortfall. Each side counts on its own, so a judge that passes everything can't look accurate. A side is measured
    once some grader has MINIMUM swipes on it, and then every grader with that many must clear the bar there. An
    unmeasured bad side is "unmeasured": the prompt may rarely break the rule, so the judge guards the run untested. An
    unmeasured good side is "untrusted": a judge nobody has seen pass anything is unsafe to optimize against."""
    untrusted: list[str] = []
    warned: list[str] = []
    unmeasured: list[str] = []
    for side, cards in (("good", "good cards"), ("bad", "bad cards for this rule")):
        counted = {grader: getattr(row, side) for grader, row in agreements.items() if getattr(row, side).total >= MINIMUM}
        if not counted:
            most = max((getattr(row, side).total for row in agreements.values()), default=0)
            if side == "good":
                untrusted.append(f"only {most} good swipes; swipe at least {MINIMUM - most} more")
            else:
                unmeasured.append(f"only {most} bad swipes for this rule, so it guards the run untested; swipe at least {MINIMUM - most} more to measure it")
        for grader, s in counted.items():
            percent = round(100 * s.agreed / s.total)
            if 100 * s.agreed < WARNED * s.total:
                untrusted.append(
                    f"fails outputs {grader} called good ({percent}%); sharpen the rubric"
                    if side == "good"
                    else f"misses problems {grader} flagged ({percent}%); sharpen the rubric or swipe more examples"
                )
            elif 100 * s.agreed < TRUSTED * s.total:
                warned.append(f"agrees with {grader} on {percent}% of {cards}; below {TRUSTED}% is a warning")
    if untrusted:
        return "untrusted", untrusted + unmeasured
    if unmeasured:
        return "unmeasured", warned + unmeasured
    return ("warn", warned) if warned else ("trusted", [])


def optimize_gate(gates: dict[str, tuple[str, list[str]]]) -> tuple[bool, list[str]]:
    """Whether optimizing may start against these judges' gates, and what to tell the user: every untrusted judge's
    advice when it may not, else every warned and unmeasured judge's."""
    refused = [f"{name}: {advice}" for name, (status, advices) in gates.items() if status == "untrusted" for advice in advices]
    if refused:
        return False, refused
    return True, [f"{name}: {advice}" for name, (status, advices) in gates.items() if status in ("warn", "unmeasured") for advice in advices]
