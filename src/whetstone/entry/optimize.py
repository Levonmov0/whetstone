"""An optimizing run: GEPA rewrites the editable part against the suite, and the winner is tried on held-back cases."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from whetstone.entry.suite import Stop, Suite
from whetstone.features.optimize.core import RoleCost, SplitError, case_score, length_factor, run_report, split_cases, swap_editable
from whetstone.platform.gepa import optimize
from whetstone.platform.model import ModelCall, ModelError, ModelResult

ROLES = ("generation", "judge", "rewrite")


class Meter:
    """Counts every model call of a run by role: calls, tokens and the dollars a call reported."""

    def __init__(self) -> None:
        self.spent = {role: RoleCost(0, 0, 0, 0.0) for role in ROLES}

    def wrap(self, role: str, call: ModelCall) -> ModelCall:
        def metered(request: dict[str, Any]) -> ModelResult:
            result = call(request)
            before = self.spent[role]
            dollars = None if before.dollars is None or result.cost_usd is None else before.dollars + result.cost_usd
            self.spent[role] = RoleCost(before.calls + 1, before.input_tokens + result.input_tokens, before.output_tokens + result.output_tokens, dollars)
            return result

        return metered


def run_optimize(suite: Suite, prompt_dir: Path, editable: str, model: str, rewrite: ModelCall, budget: int, run_id: str, meter: Meter) -> int:
    """`suite`'s model and judges are already metered by `meter`."""
    try:
        train, select, held = split_cases([case_id for case_id, _, _ in suite.requests])
    except SplitError as e:
        raise Stop(str(e)) from None
    requests = {case_id: (case_input, request) for case_id, case_input, request in suite.requests}
    generate = meter.wrap("generation", suite.model)
    rewrite = meter.wrap("rewrite", rewrite)

    def score(text: str, case_id: str) -> tuple[float, str, Any, Any, dict[str, list[str]]]:
        case_input, request = requests[case_id]
        output = generate({**swap_editable(request, editable, text), "model": model}).output
        failures = suite.score(case_id, case_input, output)
        value, feedback = case_score(failures, length_factor(len(editable), len(text)))
        return value, feedback, case_input, output, failures

    versions: list[tuple[str, float]] = []  # each version scored on every selection case, and its average there

    def evaluate(text: str, batch: list[str]) -> list[tuple[float, str, Any, Any]]:
        results = [score(text, case_id)[:4] for case_id in batch]
        if sorted(batch) == sorted(select):
            versions.append((text, sum(r[0] for r in results) / len(results)))
        return results

    rewrite_errors: list[str] = []

    def reflect(prompt: str) -> str:
        try:
            return str(rewrite({"max_tokens": 8000, "messages": [{"role": "user", "content": prompt}]}).output)
        except ModelError as e:
            rewrite_errors.append(str(e))  # GEPA logs a failed rewrite and goes on, so it is kept to say why
            raise

    optimize(editable, train, select, evaluate, reflect, budget, stop=lambda: False)
    if not any(text != editable for text, _ in versions):
        why = f"; the last rewrite failed: {rewrite_errors[-1]}" if rewrite_errors else ""
        print(f"GEPA produced no new version{why}")
        return 1
    best = max(versions, key=lambda version: version[1])[0]

    held_failures: dict[str, dict[str, dict[str, list[str]]]] = {"original": {}, "candidate": {}}
    totals = {"original": 0.0, "candidate": 0.0}
    for version, text in (("original", editable), ("candidate", best)):
        for case_id in held:
            value, _, _, _, failures = score(text, case_id)
            held_failures[version][case_id] = failures
            totals[version] += value
    average = {version: total / len(held) for version, total in totals.items()}

    folder = prompt_dir / "runs" / f"run-{run_id}"
    folder.mkdir(parents=True)
    (folder / "split.json").write_text(json.dumps({"training": train, "selection": select, "held_back": held}, indent=2))
    (folder / "candidate.txt").write_text(best)
    (folder / "cost.json").write_text(json.dumps({role: asdict(cost) for role, cost in meter.spent.items()}, indent=2))
    (folder / "report.md").write_text(run_report(prompt_dir.name, editable, best, held_failures, average, meter.spent, []))
    return 0
