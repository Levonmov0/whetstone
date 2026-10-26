import argparse
import fcntl
import ipaddress
import json
import secrets
import socket
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import qrcode

from whetstone.features.cases.core import provider_refusal
from whetstone.features.cases.load import CaseError, load_cases
from whetstone.features.cases.sources import SourceError, add_source
from whetstone.features.checks.core import CaseResult, covered_reasons, judge_failures, judge_request, report, uncovered_reasons
from whetstone.features.checks.load import CheckLoadError, code_check_names, load_checks, load_judges
from whetstone.features.grading.core import disagreements
from whetstone.features.grading.store import add_label, load_labels, private_dir, save_deck
from whetstone.features.workspace.core import request_differences, request_problem
from whetstone.features.workspace.load import PromptError, PromptSettings, find_workspace, judge_model, load_prompt, phone_access, prompt_names, repo_providers
from whetstone.platform.anthropic import anthropic_model
from whetstone.platform.config import MissingKey, load_key
from whetstone.platform.daemon import command_line, is_running, start_detached, stop, write_private
from whetstone.platform.harness import HarnessError, build_request
from whetstone.platform.model import ModelCall, ModelError
from whetstone.platform.network import TailscaleError, TailscaleMissing, lan_address, tailscale_address

MakeModel = Callable[[PromptSettings], ModelCall]
MakeJudge = Callable[[Path], ModelCall]  # takes the workspace, whose .env holds the judge key


class Stop(Exception):
    """A broken setup: the message is printed and the command exits 2."""


def no_judge(_workspace: Path) -> ModelCall:
    raise NotImplementedError


def run(argv: list[str], make_model: MakeModel, make_judge: MakeJudge = no_judge) -> int:
    parser = argparse.ArgumentParser(prog="whetstone")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="run every case through the prompt and its checks")
    verify = commands.add_parser("verify-harness", help="compare the harness's request with a real production request")
    verify.add_argument("--case", required=True, help="the case id to build the request from")
    verify.add_argument("--expected", type=Path, required=True, help="a JSON file holding the request production sent")
    reasons = commands.add_parser("reasons", help="list left-swipe reasons that no check stands for yet")
    disagree = commands.add_parser("disagreements", help="list the cards graders disagree on")
    settle = commands.add_parser("settle", help="record your call on a card graders disagree on")
    serve = commands.add_parser("serve", help="start the swipe server in the background and show its QR code")
    source = commands.add_parser("add-source", help="make a private folder for one real-data source and record its consent")
    for command in (check, verify, source, disagree, settle, reasons):
        command.add_argument("prompt")
    serve.add_argument("prompt", nargs="?")
    serve.add_argument("--stop", action="store_true", help="stop the running swipe server")
    for command in (check, verify, source, disagree, settle, serve, reasons):
        command.add_argument("--workspace", type=Path, help="the workspace folder, when it is not ./ or ./whetstone/")
    serve.add_argument("--host", help="the address to listen on")
    settle.add_argument("card", help="the card id, as disagreements prints it")
    settle.add_argument("verdict", choices=["good", "bad"])
    settle.add_argument("--grader", required=True, help="your name")
    settle.add_argument("--note", default="", help="the rule this settles, in your words")
    source.add_argument("source", help="the source's folder name, such as diary")
    source.add_argument("--consented-by", required=True, help="who consented")
    source.add_argument("--consented-on", required=True, help="the date they consented, such as 2026-10-26")
    args = parser.parse_args(argv)

    try:
        if args.command == "serve" and args.stop:
            return stop_server(args.workspace)
        prompt = find_prompt(args.workspace, args.prompt)
        if args.command == "verify-harness":
            return verify_harness(prompt, args.case, args.expected)
        if args.command == "reasons":
            return list_reasons(prompt)
        if args.command == "disagreements":
            return list_disagreements(prompt)
        if args.command == "serve":
            return start_server(prompt, args.host)
        if args.command == "settle":
            return settle_card(prompt, args.card, args.verdict, args.grader, args.note)
        if args.command == "add-source":
            try:
                add_source(prompt.dir, args.source, args.consented_by, args.consented_on)
            except SourceError as e:
                raise Stop(str(e)) from None
            return 0
        return check_prompt(prompt, make_model, make_judge)
    except Stop as e:
        print(e, file=sys.stderr)
        return 2


def find_prompt(explicit_workspace: Path | None, name: str) -> PromptSettings:
    workspace = workspace_or_stop(explicit_workspace)
    names = prompt_names(workspace)
    if name not in names:
        raise Stop(f"no prompt named {name}; prompts: {', '.join(names) or 'none yet'}")
    try:
        return load_prompt(workspace, name)
    except PromptError as e:
        raise Stop(str(e)) from None


def workspace_or_stop(explicit_workspace: Path | None) -> Path:
    workspace = find_workspace(Path.cwd(), explicit_workspace)
    if workspace is None:
        raise Stop("no Whetstone workspace found; run /whetstone:init or pass --workspace")
    return workspace


def build(prompt: PromptSettings, case_id: str, case_json: str) -> Any:
    try:
        return build_request(prompt.harness, prompt.workspace, case_json)
    except HarnessError as e:
        raise Stop(f"case {case_id}: {e}") from None


def check_prompt(prompt: PromptSettings, make_model: MakeModel, make_judge: MakeJudge) -> int:
    if prompt.editable is None:
        raise Stop(f'{prompt.dir / "prompt.toml"} has no "editable" part yet')
    # Every request is built and vetted before the first model call, so a broken harness costs nothing.
    try:
        cases = load_cases(prompt.dir)
    except CaseError as e:
        raise Stop(str(e)) from None
    if not cases:
        raise Stop(f"no cases in {prompt.dir / 'cases'}")
    has_private = any(case_id.startswith("private/") for case_id, _ in cases)
    try:
        providers = repo_providers(prompt.workspace)
    except PromptError as e:
        raise Stop(str(e)) from None
    if refusal := provider_refusal(prompt.provider, providers, has_private):
        raise Stop(refusal)
    requests: list[tuple[str, Any, Any]] = []
    for case_id, case_json in cases:
        try:
            case_input = json.loads(case_json)
        except ValueError as e:
            raise Stop(f"case {case_id} is not valid JSON: {e}") from None
        request = build(prompt, case_id, case_json)
        if problem := request_problem(request, case_id, prompt.model, prompt.editable):
            raise Stop(problem)
        requests.append((case_id, case_input, request))

    try:
        checks = load_checks(prompt.dir)
        judges = load_judges(prompt.dir)
    except CheckLoadError as e:
        raise Stop(str(e)) from None
    try:
        judged_by = judge_model(prompt.workspace) if judges else ""
    except PromptError as e:
        raise Stop(str(e)) from None
    try:
        model = make_model(prompt)
    except MissingKey as e:
        raise Stop(str(e)) from None
    judge = make_judge(prompt.workspace) if judges else None
    results: list[CaseResult] = []
    cards: list[dict[str, Any]] = []
    for case_id, case_input, request in requests:
        try:
            output = model(request).output
        except ModelError as e:
            raise Stop(f"model call failed on case {case_id}: {e}") from None
        failures: dict[str, list[str]] = {}
        for name, check in checks.items():
            try:
                messages = check(output)
            except Exception as e:  # a check is the workspace's own code; any crash means the suite is broken
                raise Stop(f"check {name} crashed on case {case_id}: {e}") from None
            if not isinstance(messages, list) or not all(isinstance(m, str) for m in cast(list[Any], messages)):
                raise Stop(f"check {name} returned {messages!r} on case {case_id}; a check returns a list of failure messages")
            failures[name] = cast(list[str], messages)
        for name, rubric in judges.items():
            assert judge
            reply = judge(judge_request(rubric, judged_by, case_input, output)).output
            failures[f"{name} (judge)"] = judge_failures(rubric, reply)
        results.append(CaseResult(case_id, failures))
        caught_by = [name.removesuffix(" (judge)") for name, messages in failures.items() if messages]
        cards.append({"case_id": case_id, "input": case_input, "output": output, "caught_by": caught_by})
    save_deck(prompt.workspace, prompt.dir.name, cards)
    lines, code = report(results, [*checks, *(f"{name} (judge)" for name in judges)])
    print("\n".join(lines))
    return code


def verify_harness(prompt: PromptSettings, case_id: str, expected_file: Path) -> int:
    cases = dict(load_cases(prompt.dir))
    if case_id not in cases:
        raise Stop(f"no case named {case_id}; cases: {', '.join(cases)}")
    case_json = cases[case_id]
    try:
        expected = json.loads(expected_file.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise Stop(f"can't read the production request in {expected_file}: {e}") from None
    differences = request_differences(build(prompt, case_id, case_json), expected)
    if not differences:
        print("harness matches the production request")
        return 0
    print("\n".join(f"{path} differs" for path in differences))
    return 1


def running_server(workspace: Path) -> dict[str, Any] | None:
    """The state of this workspace's swipe server when it is still running, else None (and stale state is removed).
    A pid alone isn't proof: the OS reuses them, so the process must also be our server for this workspace."""
    state_file = workspace / ".whetstone" / "serve.json"
    if not state_file.is_file():
        return None
    try:
        state = json.loads(state_file.read_text())
        pid = state["pid"]
    except (ValueError, KeyError, TypeError):
        state, pid = None, None  # unreadable: whatever wrote it is not a server we can find
    command = command_line(pid) if isinstance(pid, int) and is_running(pid) else ""
    if state and "whetstone.entry.serve_main" in command and str(workspace) in command:
        return state
    state_file.unlink()
    return None


def start_server(prompt: PromptSettings, explicit_host: str | None) -> int:
    folder = private_dir(prompt.workspace)
    # One `serve` at a time per workspace, so two can't both find no server and both start one.
    with (folder / "serve.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _start_server(prompt, explicit_host, folder)


def _start_server(prompt: PromptSettings, explicit_host: str | None, folder: Path) -> int:
    state_file = folder / "serve.json"
    if state := running_server(prompt.workspace):
        if state["prompt"] != prompt.dir.name:
            raise Stop(f"already serving {state['prompt']}; run whetstone serve --stop first")
        show_link(state["url"])
        return 0
    host = explicit_host or phone_host(prompt.workspace)
    if _every_interface(host):
        raise Stop(f"--host must be one address, not every interface ({host})")
    token = secrets.token_urlsafe(32)
    # This process binds the socket and hands it over, so the port is known before the server starts and never races.
    try:
        listener = socket.create_server((host, 0))
    except OSError as e:
        raise Stop(f"can't listen on {host}: {e.strerror or e}") from None
    port = listener.getsockname()[1]
    argv = [sys.executable, "-m", "whetstone.entry.serve_main", str(prompt.workspace), prompt.dir.name, str(listener.fileno())]
    pid = start_detached(argv, token + "\n", folder / "server.log", pass_fds=(listener.fileno(),))
    listener.close()
    url = f"http://{host}:{port}/#t={token}"  # after the #, so the token is never sent in a URL or logged
    write_private(state_file, json.dumps({"pid": pid, "host": host, "port": port, "prompt": prompt.dir.name, "token": token, "url": url}))
    show_link(url)
    return 0


def _every_interface(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_unspecified
    except ValueError:
        return host == ""


def phone_host(workspace: Path) -> str:
    try:
        access = phone_access(workspace)
    except PromptError as e:
        raise Stop(str(e)) from None
    if access == "tailscale":
        try:
            return tailscale_address()
        except TailscaleMissing:
            raise Stop("phone.access is tailscale but the tailscale command was not found") from None
        except TailscaleError as e:
            raise Stop(f"tailscale is not connected: {e}") from None
    address = lan_address()
    if address is None:
        raise Stop("no Wi-Fi or LAN address found; pass --host")
    return address


def stop_server(explicit_workspace: Path | None) -> int:
    workspace = workspace_or_stop(explicit_workspace)
    state = running_server(workspace)
    if state is None:
        print("no server running")
        return 0
    stop(state["pid"])
    (workspace / ".whetstone" / "serve.json").unlink(missing_ok=True)
    print("stopped the swipe server")
    return 0


def show_link(url: str) -> None:
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.print_ascii(out=sys.stdout, invert=True)
    print(url)


def list_reasons(prompt: PromptSettings) -> int:
    try:
        judges = load_judges(prompt.dir)
    except CheckLoadError as e:
        raise Stop(str(e)) from None
    covered = covered_reasons(code_check_names(prompt.dir), judges)
    uncovered = uncovered_reasons(load_labels(prompt.dir), covered)
    print("\n".join(f"{count}  {reason}" for reason, count in uncovered) if uncovered else "every reason has a check")
    return 0


def list_disagreements(prompt: PromptSettings) -> int:
    labels = load_labels(prompt.dir)
    queued = disagreements(labels)
    for card in queued:
        latest = {label["grader"]: label for label in labels if label["card_id"] == card}
        print(f"{card}  " + "  ".join(_verdict(label) for label in latest.values()))
    print(f"{len(queued)} card{'' if len(queued) == 1 else 's'} to settle" if queued else "nothing to settle")
    return 0


def settle_card(prompt: PromptSettings, card: str, verdict: str, grader: str, note: str) -> int:
    swiped = [label for label in load_labels(prompt.dir) if label["card_id"] == card]
    if not swiped:
        raise Stop(f"no labels for card {card}")
    swipe: dict[str, Any] = {"grader": grader, "verdict": verdict, "reasons": [], "note": note, "settled": True, "at": datetime.now(UTC).isoformat()}
    add_label(prompt.dir, {**swiped[-1], **swipe})
    return 0


def _verdict(label: dict[str, Any]) -> str:
    reasons = f" ({', '.join(label['reasons'])})" if label["reasons"] else ""
    note = f" {json.dumps(label['note'], ensure_ascii=False)}" if label["note"] else ""
    return f"{label['grader']}: {label['verdict']}{reasons}{note}"


def production_model(settings: PromptSettings) -> ModelCall:
    return anthropic_model(load_key(settings.workspace, "GENERATION_API_KEY"))


def main() -> None:
    sys.exit(run(sys.argv[1:], make_model=production_model))
