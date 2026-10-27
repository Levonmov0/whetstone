"""Pure rules for an optimizing run: no I/O, environment or SDKs."""

import hashlib
import re
from collections import Counter
from dataclasses import dataclass


class SplitError(Exception):
    pass


def split_cases(case_ids: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Training, selection and held-back case ids, 40/25/35. Each case's place comes from a hash of its id, so a case
    held back in one run stays held back in the next."""
    if len(case_ids) < 3:
        raise SplitError(f"a run needs at least 3 cases; this prompt has {len(case_ids)}")
    ordered = sorted(case_ids, key=lambda case_id: hashlib.sha256(case_id.encode()).hexdigest())
    train, select = round(0.4 * len(ordered)), round(0.25 * len(ordered))
    return ordered[:train], ordered[train : train + select], ordered[train + select :]


MAX_GROWTH = 1.5


def length_factor(original: int, length: int) -> float:
    """What a version's score is multiplied by: 1 up to 1.5 times the original's length, then less the longer it gets,
    so a version three times as long scores half."""
    return min(1.0, MAX_GROWTH * original / length)


# {{name}} and ${name}; a lone {name} is left out, as it would match the JSON prompts show their output in.
PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}|\$\{[^{}]+\}")


def placeholder_problem(original: str, candidate: str) -> str | None:
    """Why a version can't be applied to the source because it dropped or changed a placeholder, or None."""
    before, after = Counter(PLACEHOLDER.findall(original)), Counter(PLACEHOLDER.findall(candidate))
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
