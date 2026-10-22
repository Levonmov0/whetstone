import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from whetstone.features.cases.load import load_cases
from whetstone.features.checks.core import CaseResult, report
from whetstone.features.checks.load import load_checks
from whetstone.features.workspace.core import request_differences, request_problem
from whetstone.features.workspace.load import PromptSettings, find_workspace, load_prompt, prompt_names
from whetstone.platform.anthropic import anthropic_model
from whetstone.platform.config import MissingKey, load_key
from whetstone.platform.harness import HarnessError, build_request
from whetstone.platform.model import ModelCall

MakeModel = Callable[[PromptSettings], ModelCall]


class Stop(Exception):
    """A broken setup: the message is printed and the command exits 2."""


def run(argv: list[str], make_model: MakeModel) -> int:
    parser = argparse.ArgumentParser(prog="whetstone")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="run every case through the prompt and its checks")
    verify = commands.add_parser("verify-harness", help="compare the harness's request with a real production request")
    verify.add_argument("--case", required=True, help="the case id to build the request from")
    verify.add_argument("--expected", type=Path, required=True, help="a JSON file holding the request production sent")
    for command in (check, verify):
        command.add_argument("prompt")
        command.add_argument("--workspace", type=Path, help="the workspace folder, when it is not ./ or ./whetstone/")
    args = parser.parse_args(argv)

    try:
        prompt = find_prompt(args.workspace, args.prompt)
        if args.command == "verify-harness":
            return verify_harness(prompt, args.case, args.expected)
        return check_prompt(prompt, make_model)
    except Stop as e:
        print(e, file=sys.stderr)
        return 2


def find_prompt(explicit_workspace: Path | None, name: str) -> PromptSettings:
    workspace = find_workspace(Path.cwd(), explicit_workspace)
    if workspace is None:
        raise Stop("no Whetstone workspace found; run /whetstone:init or pass --workspace")
    names = prompt_names(workspace)
    if name not in names:
        raise Stop(f"no prompt named {name}; prompts: {', '.join(names)}")
    return load_prompt(workspace, name)


def build(prompt: PromptSettings, case_id: str, case_json: str) -> Any:
    try:
        return build_request(prompt.harness, prompt.workspace, case_json)
    except HarnessError as e:
        raise Stop(f"case {case_id}: {e}") from None


def check_prompt(prompt: PromptSettings, make_model: MakeModel) -> int:
    # Every request is built and vetted before the first model call, so a broken harness costs nothing.
    requests: list[tuple[str, Any]] = []
    for case_id, case_json in load_cases(prompt.dir):
        request = build(prompt, case_id, case_json)
        if problem := request_problem(request, case_id, prompt.model, prompt.editable):
            raise Stop(problem)
        requests.append((case_id, request))

    try:
        model = make_model(prompt)
    except MissingKey as e:
        raise Stop(str(e)) from None
    checks = load_checks(prompt.dir)
    results: list[CaseResult] = []
    for case_id, request in requests:
        output = model(request).output
        failures: dict[str, list[str]] = {}
        for name, check in checks.items():
            try:
                failures[name] = check(output)
            except Exception as e:  # a check is the workspace's own code; any crash means the suite is broken
                raise Stop(f"check {name} crashed on case {case_id}: {e}") from None
        results.append(CaseResult(case_id, failures))
    lines, code = report(results, list(checks))
    print("\n".join(lines))
    return code


def verify_harness(prompt: PromptSettings, case_id: str, expected_file: Path) -> int:
    case_json = dict(load_cases(prompt.dir))[case_id]
    differences = request_differences(build(prompt, case_id, case_json), json.loads(expected_file.read_text()))
    if not differences:
        print("harness matches the production request")
        return 0
    print("\n".join(f"{path} differs" for path in differences))
    return 1


def production_model(settings: PromptSettings) -> ModelCall:
    return anthropic_model(load_key(settings.workspace, "GENERATION_API_KEY"))


def main() -> None:
    sys.exit(run(sys.argv[1:], make_model=production_model))
