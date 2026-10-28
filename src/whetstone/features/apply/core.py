"""Pure rules for applying a run's candidate to the source: no I/O, environment or SDKs."""


def apply_method(source_text: str, editable: str) -> str:
    """How a candidate reaches the source: "exact" when the editable part is one fixed string in it."""
    return "exact"
