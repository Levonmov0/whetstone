import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from whetstone.features.cases.load import load_cases
from whetstone.features.checks.core import CaseResult, report
from whetstone.features.checks.load import load_checks
from whetstone.features.workspace.core import request_problem
from whetstone.features.workspace.load import PromptSettings, find_workspace, load_prompt, prompt_names
from whetstone.platform.harness import HarnessError, build_request
from whetstone.platform.model import ModelCall


def run(argv: list[str], make_model: Callable[[PromptSettings], ModelCall]) -> int:
    parser = argparse.ArgumentParser(prog="whetstone")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="run every case through the prompt and its checks")
    check.add_argument("prompt")
    check.add_argument("--workspace", type=Path, help="the workspace folder, when it is not ./ or ./whetstone/")
    args = parser.parse_args(argv)

    workspace = find_workspace(Path.cwd(), args.workspace)
    if workspace is None:
        print("no Whetstone workspace found; run /whetstone:init or pass --workspace", file=sys.stderr)
        return 2
    names = prompt_names(workspace)
    if args.prompt not in names:
        print(f"no prompt named {args.prompt}; prompts: {', '.join(names)}", file=sys.stderr)
        return 2
    prompt = load_prompt(workspace, args.prompt)
    # Every request is built and vetted before the first model call, so a broken harness costs nothing.
    requests: list[tuple[str, Any]] = []
    for case_id, case_json in load_cases(prompt.dir):
        try:
            request = build_request(prompt.harness, workspace, case_json)
        except HarnessError as e:
            print(f"case {case_id}: {e}", file=sys.stderr)
            return 2
        if problem := request_problem(request, case_id, prompt.model, prompt.editable):
            print(problem, file=sys.stderr)
            return 2
        requests.append((case_id, request))

    model = make_model(prompt)
    checks = load_checks(prompt.dir)
    results: list[CaseResult] = []
    for case_id, request in requests:
        output = model(request).output
        failures: dict[str, list[str]] = {}
        for name, check in checks.items():
            try:
                failures[name] = check(output)
            except Exception as e:  # a check is the workspace's own code; any crash means the suite is broken
                print(f"check {name} crashed on case {case_id}: {e}", file=sys.stderr)
                return 2
        results.append(CaseResult(case_id, failures))
    lines, code = report(results, list(checks))
    print("\n".join(lines))
    return code
