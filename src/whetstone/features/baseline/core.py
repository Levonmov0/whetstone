"""Pure rules for a baseline: no I/O, environment or SDKs."""


def baseline_verdict(results: dict[str, dict[str, bool]]) -> str:
    """Whether a model change alone fixes most of the production model's failures. `results` maps each model, the
    production one first, to whether each case passed every check."""
    production, *others = results
    failing = [case for case, passed in results[production].items() if not passed]
    if not failing:
        return f"{production} passes every check on every case; a model change has nothing to fix."
    fixed = {model: sum(results[model][case] for case in failing) for model in others}
    best = max(others, key=lambda model: fixed[model])  # the first listed, on a tie
    passes = f"passes {fixed[best]} of the {len(failing)} cases {production} fails."
    broken = sum(not results[best][case] for case, passed in results[production].items() if passed)
    also = f" It fails {broken} case{'' if broken == 1 else 's'} {production} passes." if broken else ""
    if 2 * fixed[best] > len(failing):
        return f"Yes: a model change alone fixes most failures. {best} {passes}{also}"
    return f"No: no listed model fixes most failures. The best, {best}, {passes} The prompt is the problem.{also}"
