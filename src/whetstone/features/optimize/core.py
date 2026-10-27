"""Pure rules for an optimizing run: no I/O, environment or SDKs."""


class SplitError(Exception):
    pass


def split_cases(case_ids: list[str]) -> tuple[list[str], list[str], list[str]]:
    raise NotImplementedError
