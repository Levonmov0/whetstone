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


def warnings(tally: dict[str, dict[str, int]], within_noise: bool) -> list[str]:
    """What the user should hear before a candidate reaches the source. `tally` is each version's good, bad and skip
    swipes on the run's blind deck."""
    found: list[str] = []
    if not any(sum(counts.values()) for counts in tally.values()):
        found.append("no blind swipe yet: nobody has compared the candidate with the original without knowing which is which")
    original, candidate = (tally[version]["good"] for version in ("original", "candidate"))
    if original > candidate:
        found.append(f"the blind swipe preferred the original: {original} good swipes against the candidate's {candidate}")
    if within_noise:
        found.append("the held-back result is within noise: two runs of the same prompt can differ this much")
    return found


def replace_once(text: str, original: str, candidate: str) -> str | None:
    """`text` with `original` replaced by `candidate`, or None when `original` isn't in it exactly once."""
    return text.replace(original, candidate) if text.count(original) == 1 else None
