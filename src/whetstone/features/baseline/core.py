"""Pure rules for a baseline: no I/O, environment or SDKs."""

from typing import Any


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


def baseline_report(prompt: str, check_names: list[str], runs: dict[str, list[dict[str, list[str]]]], tokens: dict[str, tuple[int, int]]) -> str:
    """The report's text. `runs` maps each model, production first, to each case's failures per check; `tokens` to its
    input and output tokens."""
    passed = {model: {str(i): not any(failures.values()) for i, failures in enumerate(cases)} for model, cases in runs.items()}
    header = ["model", "every check", *check_names, "input tokens", "output tokens"]
    lines = [f"# Baseline: {prompt}", "", baseline_verdict(passed), "", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for model, cases in runs.items():
        counts = [f"{sum(passed[model].values())}/{len(cases)}", *(f"{sum(not c[name] for c in cases)}/{len(cases)}" for name in check_names)]
        lines.append("| " + " | ".join([model, *counts, *map(str, tokens[model])]) + " |")
    return "\n".join(lines) + "\n"


def swipe_section(report: str, labels: list[dict[str, Any]], deck_id: str, tag_models: dict[str, str]) -> str:
    """The report with its swipes section written afresh: per model, the latest good, bad and skip swipes of each
    grader on this run's cards, `<deck-id>:<case-id>:<tag>`. Models come in `tag_models`' order, production first."""
    latest: dict[tuple[str, str], str] = {}
    for label in sorted(labels, key=lambda label: str(label.get("at", ""))):
        tag = str(label["card_id"]).rsplit(":", 1)[-1]
        if label["card_id"].startswith(f"{deck_id}:") and tag in tag_models:
            latest[label["grader"], tag] = label["verdict"]
    tally = {model: {"good": 0, "bad": 0, "skip": 0} for model in tag_models.values()}
    for (_grader, tag), verdict in latest.items():
        tally[tag_models[tag]][verdict] += 1
    lines = [f"- {model}: good {t['good']}, bad {t['bad']}, skip {t['skip']}" for model, t in tally.items()]
    return report.split("\n## Swipes\n")[0].rstrip("\n") + "\n\n## Swipes\n\n" + "\n".join(lines) + "\n"
