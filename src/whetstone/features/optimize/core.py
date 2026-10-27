"""Pure rules for an optimizing run: no I/O, environment or SDKs."""

import hashlib


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


def length_factor(original: int, length: int) -> float:
    raise NotImplementedError
