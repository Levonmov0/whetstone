"""Pure rules for applying a run's candidate to the source: no I/O, environment or SDKs."""


def apply_method(source_text: str, editable: str, source: str) -> tuple[str, str | None]:
    """How a candidate reaches the source, and why when it can't be a plain replacement: "exact" when the editable
    part is one fixed string in the source file, else "code-edit"."""
    times = source_text.count(editable)
    if times == 1:
        return "exact", None
    return "code-edit", f"the editable part is found {times} times in {source}, so applying a candidate means editing the code"


def run_line(run: str, model: str, production_model: str, cases: int, original_clean: int, candidate_clean: int) -> str:
    """The run apply is about to use, said before anything else."""
    on = "production model" if model == production_model else f"cheap model {model}"
    return f"{run}, {on}, {candidate_clean}/{cases} held-back passing vs {original_clean}/{cases} original"
