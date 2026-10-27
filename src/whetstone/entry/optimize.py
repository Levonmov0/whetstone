"""An optimizing run: GEPA rewrites the editable part against the suite, and the winner is tried on held-back cases."""

import json
import random
import secrets
from dataclasses import asdict
from typing import Any

from whetstone.entry.suite import Stop, Suite, card
from whetstone.features.cases.load import CaseError, load_cases
from whetstone.features.grading.store import save_deck
from whetstone.features.optimize.core import EstimateError, RoleCost, SplitError, case_score, estimate, length_factor, placeholder_problem, progress_line, run_report, split_cases, stop_for_cap, stuck_reasons, swap_editable
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

    def total(self) -> float:
        """The dollars spent so far that are known."""
        return sum(cost.dollars or 0.0 for cost in self.spent.values())

    def per_generation(self) -> float:
        """What one scored output has cost on average: its generation and its judges."""
        generation, judge = self.spent["generation"], self.spent["judge"]
        return ((generation.dollars or 0.0) + (judge.dollars or 0.0)) / generation.calls if generation.calls else 0.0


class CapReached(Exception):
    pass


def run_optimize(suite: Suite, prompt: PromptSettings, model: str, rewrite: ModelCall, rewrite_model: str | None, budget: int, run_id: str, meter: Meter, cap: float | None = None) -> int:
    """`suite`'s model and judges are already metered by `meter`. With a `cap`, GEPA stops while the held-back
    scoring still fits under it, and the best version so far is kept."""
    prompt_dir, editable = prompt.dir, prompt.editable
    assert editable is not None  # the suite was prepared, which needs it
    try:
        train, select, held = split_cases([case_id for case_id, _, _ in suite.requests])
    except SplitError as e:
        raise Stop(str(e)) from None
    requests = {case_id: (case_input, request) for case_id, case_input, request in suite.requests}
    generate = meter.wrap("generation", suite.model)
    rewrite = meter.wrap("rewrite", rewrite)

    gepa_running = False

    def over_cap() -> bool:
        # The held-back cases are scored twice (original and candidate), after one more output at most.
        return gepa_running and stop_for_cap(meter.total(), (2 * len(held) + 1) * meter.per_generation(), cap)

    def score(text: str, case_id: str) -> tuple[float, str, Any, Any, dict[str, list[str]]]:
        if over_cap():
            raise CapReached()
        case_input, request = requests[case_id]
        output = generate({**swap_editable(request, editable, text), "model": model}).output
        failures = suite.score(case_id, case_input, output)
        value, feedback = case_score(failures, length_factor(len(editable), len(text)))
        return value, feedback, case_input, output, failures

    versions: list[tuple[str, float]] = []  # each version scored on every selection case, and its average there
    records: list[tuple[int, str, dict[str, list[str]]]] = []  # each such version's failures per selection case

    def evaluate(text: str, batch: list[str]) -> list[tuple[float, str, Any, Any]]:
        if problem := (placeholder_problem(editable, text) if text.strip() else "is empty"):
            # It could never be applied to the source (or says nothing), so it is scored 0 without spending a call on it.
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
            request: dict[str, Any] = {"max_tokens": 8000, "messages": [{"role": "user", "content": prompt}]}
            return str(rewrite(request | ({"model": rewrite_model} if rewrite_model else {})).output)
        except ModelError as e:
            rewrite_errors.append(str(e))  # GEPA logs a failed rewrite and goes on, so it is kept to say why
            raise

    gepa_running = True
    try:
        optimize(editable, train, select, evaluate, reflect, budget, stop=over_cap)
        capped = over_cap()  # GEPA also stops itself for the cap, between rounds
    except CapReached:
        capped = True
    gepa_running = False

    folder = prompt_dir / "runs" / f"run-{run_id}"
    folder.mkdir(parents=True)
    if any(case_id.startswith("private/") for case_id in requests):
        # Its report, split and deck name real-data cases, so the folder ignores itself, like a source folder.
        (folder / ".gitignore").write_text("*\n")
    (folder / "run.json").write_text(json.dumps({"model": model}))
    (folder / "split.json").write_text(json.dumps({"training": train, "selection": select, "held_back": held}, indent=2))

    def fail(message: str) -> int:
        """A run with no winner: said loudly, and what it spent recorded all the same."""
        print(message)
        (folder / "cost.json").write_text(json.dumps({role: asdict(cost) for role, cost in meter.spent.items()}, indent=2))
        (folder / "report.md").write_text(f"# Run: {prompt_dir.name}\n\n{message}\n")
        return 1

    if not any(text != editable for text, _ in versions):
        return fail("GEPA produced no new version" + (f"; the last rewrite failed: {rewrite_errors[-1]}" if rewrite_errors else ""))
    best = max(versions, key=lambda version: version[1])[0]  # the first, so the original, on a tie
    if best == editable:
        return fail("no new version beat the original on the selection cases")

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

    (folder / "candidate.txt").write_text(best)
    (folder / "cost.json").write_text(json.dumps({role: asdict(cost) for role, cost in meter.spent.items()}, indent=2))
    (folder / "cards.json").write_text(json.dumps(versions_by_tag, indent=2))
    report = run_report(prompt_dir.name, editable, best, held_failures, average, meter.spent, stuck_reasons(records))
    if capped:
        report += f"\nStopped at the cap (${cap:.2f}): the best version so far is the candidate.\n"
    (folder / "report.md").write_text(report)
    save_deck(prompt.workspace, prompt_dir.name, cards, run_id)
    return 0


def production_estimate(prompt: PromptSettings, budget: int, price: tuple[float, float]) -> float:
    """What a production run of `budget` GEPA generations should cost, scaled from the prompt's last cheap run."""
    cheap = [folder for folder in sorted((prompt.dir / "runs").glob("run-*")) if json.loads((folder / "run.json").read_text())["model"] != prompt.model]
    if not cheap:
        raise Stop(f"run a cheap run first: whetstone run {prompt.dir.name} --model <a cheap model>")
    spent = {role: RoleCost(**cost) for role, cost in json.loads((cheap[-1] / "cost.json").read_text()).items()}
    try:
        _train, _select, held = split_cases([case_id for case_id, _ in load_cases(prompt.dir)])
        return estimate(spent, price, budget + 2 * len(held))
    except (SplitError, EstimateError, CaseError) as e:
        raise Stop(str(e)) from None
