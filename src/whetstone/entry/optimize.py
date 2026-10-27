"""An optimizing run: GEPA rewrites the editable part against the suite, and the winner is tried on held-back cases."""

import json
import random
import secrets
from dataclasses import asdict
from typing import Any

from whetstone.entry.suite import Stop, Suite, card
from whetstone.features.grading.store import save_deck
from whetstone.features.optimize.core import RoleCost, SplitError, case_score, length_factor, placeholder_problem, progress_line, run_report, split_cases, stuck_reasons, swap_editable
from whetstone.features.workspace.load import PromptSettings
from whetstone.platform.gepa import optimize
from whetstone.platform.model import ModelCall, ModelError, ModelResult

ROLES = ("generation", "judge", "rewrite")


class Meter:
    """Counts every model call of a run by role: calls, tokens and the dollars a call reported."""

    def __init__(self, prices: dict[str, tuple[float, float]]) -> None:
        self.prices = prices
        self.spent = {role: RoleCost(0, 0, 0, 0.0) for role in ROLES}

    def _dollars(self, request: dict[str, Any], result: ModelResult) -> float | None:
        if result.cost_usd is not None:
            return result.cost_usd
        price = self.prices.get(str(request.get("model")))
        return None if price is None else (result.input_tokens * price[0] + result.output_tokens * price[1]) / 1e6

    def wrap(self, role: str, call: ModelCall) -> ModelCall:
        def metered(request: dict[str, Any]) -> ModelResult:
            result = call(request)
            before = self.spent[role]
            cost = self._dollars(request, result)
            dollars = None if before.dollars is None or cost is None else before.dollars + cost
            self.spent[role] = RoleCost(before.calls + 1, before.input_tokens + result.input_tokens, before.output_tokens + result.output_tokens, dollars)
            return result

        return metered


def run_optimize(suite: Suite, prompt: PromptSettings, model: str, rewrite: ModelCall, budget: int, run_id: str, meter: Meter) -> int:
    """`suite`'s model and judges are already metered by `meter`."""
    prompt_dir, editable = prompt.dir, prompt.editable
    assert editable is not None  # the suite was prepared, which needs it
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
    records: list[tuple[int, str, dict[str, list[str]]]] = []  # each such version's failures per selection case

    def evaluate(text: str, batch: list[str]) -> list[tuple[float, str, Any, Any]]:
        if problem := placeholder_problem(editable, text):
            # It could never be applied to the source, so it is scored 0 without spending a call on it.
            return [(0.0, f"Rejected: it {problem}. Keep every placeholder exactly as it is.", requests[case_id][0], None) for case_id in batch]
        results = [score(text, case_id) for case_id in batch]
        if sorted(batch) == sorted(select):
            average = sum(r[0] for r in results) / len(results)
            best = all(average > other for _, other in versions)
            versions.append((text, average))
            records.extend((len(versions), case_id, r[4]) for case_id, r in zip(batch, results))
            passing = sum(not messages for r in results for messages in r[4].values())
            print(progress_line(len(versions), passing, sum(len(r[4]) for r in results), best), flush=True)
        return [r[:4] for r in results]

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
    best = max(versions, key=lambda version: version[1])[0]  # the first, so the original, on a tie
    if best == editable:
        print("no new version beat the original on the selection cases")
        return 1

    held_failures: dict[str, dict[str, dict[str, list[str]]]] = {"original": {}, "candidate": {}}
    totals = {"original": 0.0, "candidate": 0.0}
    cards: list[dict[str, Any]] = []
    versions_by_tag: dict[str, str] = {}  # each card's tag -> the version that wrote it; tags name no case
    for version, text in (("original", editable), ("candidate", best)):
        for case_id in held:
            value, _, case_input, output, failures = score(text, case_id)
            held_failures[version][case_id] = failures
            totals[version] += value
            tag = secrets.token_hex(4)
            cards.append(card(case_id, case_input, output, failures) | {"tag": tag})
            versions_by_tag[tag] = version
    random.shuffle(cards)
    average = {version: total / len(held) for version, total in totals.items()}

    folder = prompt_dir / "runs" / f"run-{run_id}"
    folder.mkdir(parents=True)
    (folder / "split.json").write_text(json.dumps({"training": train, "selection": select, "held_back": held}, indent=2))
    (folder / "candidate.txt").write_text(best)
    (folder / "cost.json").write_text(json.dumps({role: asdict(cost) for role, cost in meter.spent.items()}, indent=2))
    (folder / "cards.json").write_text(json.dumps(versions_by_tag, indent=2))
    (folder / "report.md").write_text(run_report(prompt_dir.name, editable, best, held_failures, average, meter.spent, stuck_reasons(records)))
    save_deck(prompt.workspace, prompt_dir.name, cards, run_id)
    return 0
