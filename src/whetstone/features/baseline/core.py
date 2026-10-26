"""Pure rules for a baseline: no I/O, environment or SDKs."""


def baseline_verdict(results: dict[str, dict[str, bool]]) -> str:
    raise NotImplementedError
