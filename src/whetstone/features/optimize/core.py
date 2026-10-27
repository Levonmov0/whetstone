"""Pure rules for an optimizing run: no I/O, environment or SDKs."""

import hashlib
import re
from collections import Counter


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
    raise NotImplementedError
