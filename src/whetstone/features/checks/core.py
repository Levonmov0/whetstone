"""Pure rules for a check run: how results are reported and what exit code they give."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    failures: dict[str, list[str]]  # check name -> its failure messages, empty when it passed


def report(results: list[CaseResult], check_names: list[str]) -> tuple[list[str], int]:
    """The lines to print, and the exit code."""
    lines: list[str] = []
    for r in results:
        failed = {name: msgs for name, msgs in r.failures.items() if msgs}
        if not failed:
            lines.append(f"PASS {r.case_id}")
        for name, msgs in failed.items():
            lines += [f"FAIL {r.case_id}: {name}: {m}" for m in msgs]
    lines.append("")
    for name in check_names:
        passed = sum(1 for r in results if not r.failures[name])
        lines.append(f"{name}: {passed}/{len(results)}")
    clean = sum(1 for r in results if not any(r.failures.values()))
    lines.append(f"{clean} of {len(results)} cases pass every check")
    return lines, 1
