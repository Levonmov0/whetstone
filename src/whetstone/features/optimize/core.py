"""Pure rules for an optimizing run: no I/O, environment or SDKs."""

import difflib
import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, cast


class SplitError(Exception):
    pass


def split_cases(case_ids: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Training, selection and held-back case ids, about 40/25/35. Each case's set comes from a hash of its own id,
    so adding or removing other cases never moves it, and a case held back in one run stays held back in the next."""
    if len(case_ids) < 3:
        raise SplitError(f"a run needs at least 3 cases; this prompt has {len(case_ids)}")
    bucket = {case_id: int(hashlib.sha256(case_id.encode()).hexdigest(), 16) % 100 for case_id in case_ids}
    ordered = sorted(case_ids, key=lambda case_id: (bucket[case_id], case_id))
    sets: list[list[str]] = [[c for c in ordered if bucket[c] < 40], [c for c in ordered if 40 <= bucket[c] < 65], [c for c in ordered if bucket[c] >= 65]]
    middles = (20, 52, 82)
    # ponytail: a small suite can leave a set empty; it takes the nearest case from the biggest set, which may move that
    # one case when the suite grows. Past a dozen cases this rarely happens.
    for i, chosen in enumerate(sets):
        if not chosen:
            biggest = max(sets, key=len)
            moved = min(biggest, key=lambda case_id: abs(bucket[case_id] - middles[i]))
            biggest.remove(moved)
            chosen.append(moved)
    return sets[0], sets[1], sets[2]


MAX_GROWTH = 1.5


def length_factor(original: int, length: int) -> float:
    """What a version's score is multiplied by: 1 up to 1.5 times the original's length, then less the longer it gets,
    so a version three times as long scores half."""
    return min(1.0, MAX_GROWTH * original / length)


# {{name}} and ${name}; a lone {name} is left out, as it would match the JSON prompts show their output in.
PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}|\$\{[^{}]+\}")


def placeholder_problem(original: str, candidate: str, named: list[str] | None = None) -> str | None:
    """Why a version can't be applied to the source because it dropped or changed a placeholder, or None. `named` are
    the prompt's own placeholders, from its table, whatever form they take."""

    def found(text: str) -> Counter[str]:
        return Counter(PLACEHOLDER.findall(text)) + Counter({name: text.count(name) for name in named or [] if not PLACEHOLDER.fullmatch(name)})

    before, after = found(original), found(candidate)
    problems = [f"drops placeholder {p}" for p in before - after] + [f"adds placeholder {p}" for p in after - before]
    return "; ".join(problems) or None


def case_score(failures: dict[str, list[str]], factor: float) -> tuple[float, str]:
    """One output's score, the share of checks it passed times the length factor, and the feedback GEPA reflects on."""
    broken = [f"{name}: {message}" for name, messages in failures.items() for message in messages]
    passed = sum(not messages for messages in failures.values())
    feedback = "Broke these rules:\n" + "\n".join(f"- {line}" for line in broken) if broken else "All checks passed."
    return factor * passed / len(failures), feedback


@dataclass(frozen=True)
class RoleCost:
    """What one role (generation, judge or rewrite) spent in a run; dollars None when a model had no price."""

    calls: int
    input_tokens: int
    output_tokens: int
    dollars: float | None


class EstimateError(Exception):
    pass


def estimate(cheap: dict[str, RoleCost], price: tuple[float, float], planned_generations: int) -> float:
    """A production run's dollars, scaled from the prompt's last cheap run: its tokens per generation at the
    production price, and its judge and rewrite dollars, for as many generations as planned. `price` is dollars per
    million input and output tokens."""
    generation = cheap["generation"]
    scale = planned_generations / generation.calls
    per_call = (generation.input_tokens * price[0] + generation.output_tokens * price[1]) / generation.calls / 1e6
    total = planned_generations * per_call
    for role in ("judge", "rewrite"):
        dollars = cheap[role].dollars
        if dollars is None:
            raise EstimateError(f"the last cheap run's {role} cost is unknown; add its model to [prices]")
        total += dollars * scale
    return total


def stop_for_cap(spent: float, reserve: float, cap: float | None) -> bool:
    """Whether GEPA must stop so the run stays under its cap: `reserve` is what scoring the held-back cases will
    still cost. A run without a cap never stops for one."""
    return cap is not None and spent + reserve >= cap


def stuck_reasons(records: list[tuple[int, str, dict[str, list[str]]]]) -> list[str]:
    """Why checks may still fail, from every (version, case id, failures) the run scored: a check no version passed on
    a case needs more than a better prompt, and two checks that each passed a case but never together may conflict."""
    by_case: dict[str, list[dict[str, list[str]]]] = {}
    for _version, case_id, failures in records:
        by_case.setdefault(case_id, []).append(failures)
    reasons: list[str] = []
    for case_id, runs in by_case.items():
        checks = list(runs[0])
        never = [name for name in checks if all(run[name] for run in runs)]
        reasons += [f"{name} never passed on case {case_id} in any version: this needs more input data or a different model" for name in never]
        passing = [name for name in checks if name not in never]
        for i, x in enumerate(passing):
            for y in passing[i + 1 :]:
                if not any(not run[x] and not run[y] for run in runs):
                    reasons.append(f"{x} and {y} never passed together on case {case_id}: these two rules may conflict")
    return reasons


def progress_line(version: int, passing: int, total: int, best: bool) -> str:
    """Where a run stands once a version is scored on the selection cases; `passing` of `total` check results."""
    return f"version {version}: {passing} of {total} checks passing on selection cases" + (" (best so far)" if best else "")


NOISE = 0.03  # the same prompt scored 0.90 and 0.87 on two runs


def within_noise(original: float, candidate: float) -> bool:
    """Whether two average scores are as close as two runs of one prompt can be."""
    return round(abs(candidate - original), 6) <= NOISE


def run_report(
    prompt: str,
    original: str,
    candidate: str,
    held: dict[str, dict[str, dict[str, list[str]]]],
    average: dict[str, float],
    cost: dict[str, RoleCost],
    stuck: list[str],
) -> str:
    """The report's text: the original and the candidate on the held-back cases, the diff, the length change, the cost,
    and, when checks still fail, why the run may be stuck. `held` maps each version to its failures per case."""
    checks = list(next(iter(held["original"].values())))
    header = ["version", "every check", "average score", *checks]
    lines = [f"# Run: {prompt}", "", f"Held back: {len(held['original'])} cases GEPA never saw.", ""]
    lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for version, cases in held.items():
        clean = sum(not any(failures.values()) for failures in cases.values())
        counts = [f"{sum(not failures[name] for failures in cases.values())}/{len(cases)}" for name in checks]
        lines.append("| " + " | ".join([version, f"{clean}/{len(cases)}", f"{average[version]:.2f}", *counts]) + " |")
    if within_noise(average["original"], average["candidate"]):
        lines += ["", f"The average scores differ by {NOISE} or less: within noise (±{NOISE}), as two runs of one prompt can."]
    fixed = [
        name
        for name in checks
        if any(f[name] for f in held["original"].values()) and not any(f[name] for f in held["candidate"].values())
    ]
    lines += ["", f"Rules now passing on every held-back case: {', '.join(fixed) or 'none'}"]
    change = round(100 * (len(candidate) - len(original)) / len(original))
    lines += ["", f"Length: {change:+d}% ({len(original)} → {len(candidate)} chars)"]
    diff = difflib.unified_diff(original.splitlines(), candidate.splitlines(), "original", "candidate", lineterm="")
    lines += ["", "## Diff", "", "```diff", *diff, "```", "", "## Cost", ""]
    for role, spent in cost.items():
        dollars = "$ unknown" if spent.dollars is None else f"${spent.dollars:.2f}"
        lines.append(f"- {role}: {spent.calls} calls, {spent.input_tokens} input and {spent.output_tokens} output tokens, {dollars}")
    if stuck:
        lines += ["", "## Why it may be stuck", "", *(f"- {reason}" for reason in stuck)]
    return "\n".join(lines) + "\n"



def swap_editable(request: dict[str, Any], editable: str, text: str) -> dict[str, Any]:
    """The request with its editable part replaced by `text`: in the system prompt and each message's text."""

    def swap(content: Any) -> Any:
        # Content is a string or a list of blocks, of which only text blocks carry prompt text.
        if isinstance(content, str):
            return content.replace(editable, text)
        blocks = cast(list[dict[str, Any]], content)
        return [{**block, "text": block["text"].replace(editable, text)} if block.get("type") == "text" else block for block in blocks]

    swapped = {**request, "messages": [{**message, "content": swap(message["content"])} for message in request["messages"]]}
    return swapped | ({"system": swap(request["system"])} if "system" in request else {})
