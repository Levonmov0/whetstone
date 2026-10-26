import argparse
import fcntl
import ipaddress
import json
import random
import secrets
import socket
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import qrcode

from whetstone.features.baseline.core import baseline_report, swipe_section
from whetstone.features.baseline.store import card_models, latest_run, save_run
from whetstone.features.cases.core import provider_refusal
from whetstone.features.cases.load import CaseError, load_cases
from whetstone.features.cases.sources import SourceError, add_source
from whetstone.features.checks.core import CaseResult, JudgeAnswerError, Rubric, Side, agreement, covered_reasons, judge_failures, judge_gate, judge_request, report, uncovered_reasons
from whetstone.features.checks.load import Check, CheckLoadError, code_check_reasons, load_checks, load_judges
from whetstone.features.grading.core import disagreements
from whetstone.features.grading.store import add_label, load_labels, new_deck_id, private_dir, save_deck
from whetstone.features.workspace.core import request_differences, request_problem
from whetstone.features.workspace.load import PromptError, PromptSettings, find_workspace, judge_model, load_prompt, phone_access, prompt_names, repo_providers
from whetstone.platform.anthropic import anthropic_model
from whetstone.platform.config import MissingKey, load_key
from whetstone.platform.daemon import command_line, is_running, start_detached, stop, write_private
from whetstone.platform.harness import HarnessError, build_request
from whetstone.platform.model import ModelCall, ModelError
from whetstone.platform.network import TailscaleError, TailscaleMissing, lan_address, tailscale_address
from whetstone.platform.openai import openai_model

MakeModel = Callable[[PromptSettings], ModelCall]
MakeJudge = Callable[[Path], ModelCall]  # takes the workspace, whose .env holds the judge key
Ask = Callable[[str, Rubric, str, Any, Any], list[str]]  # judge name, rubric, case id, input, output -> failures


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
    baseline = commands.add_parser("baseline", help="run the prompt on several models into one blind deck, and say if a model change is the fix")
    baseline.add_argument("--models", default="", help="the models to compare with production, comma-separated")
    baseline.add_argument("--report", action="store_true", help="add the swipes so far to the latest run's report")
    agree = commands.add_parser("agreement", help="measure each judge against the swipes and say whether it can be trusted")
    reasons = commands.add_parser("reasons", help="list left-swipe reasons that no check stands for yet")
    disagree = commands.add_parser("disagreements", help="list the cards graders disagree on")
    settle = commands.add_parser("settle", help="record your call on a card graders disagree on")
    serve = commands.add_parser("serve", help="start the swipe server in the background and show its QR code")
    source = commands.add_parser("add-source", help="make a private folder for one real-data source and record its consent")
    for command in (check, verify, source, disagree, settle, reasons, agree, baseline):
        command.add_argument("prompt")
    serve.add_argument("prompt", nargs="?")
    serve.add_argument("--stop", action="store_true", help="stop the running swipe server")
    for command in (check, verify, source, disagree, settle, serve, reasons, agree, baseline):
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
        if args.command == "baseline" and args.report:
            return refresh_baseline_report(prompt)
        if args.command == "baseline":
            return run_baseline(prompt, [m for m in args.models.split(",") if m], make_model, make_judge)
        if args.command == "agreement":
            return show_agreement(prompt, make_judge)
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


@dataclass(frozen=True)
class Suite:
    """A prompt's vetted requests and its checks, ready to run: everything that can stop a run is checked by then."""

    requests: list[tuple[str, Any, Any]]  # case id, case input, the harness's request
    checks: dict[str, Check]
    judges: dict[str, Rubric]
    ask: Ask | None
    model: ModelCall

    def check_names(self) -> list[str]:
        return [*self.checks, *(f"{name} (judge)" for name in self.judges)]

    def score(self, case_id: str, case_input: Any, output: Any) -> dict[str, list[str]]:
        """Each check's failure messages on one output, empty when it passed; judges are named "<name> (judge)"."""
        failures: dict[str, list[str]] = {}
        for name, check in self.checks.items():
            try:
                messages = check(output)
            except Exception as e:  # a check is the workspace's own code; any crash means the suite is broken
                raise Stop(f"check {name} crashed on case {case_id}: {e}") from None
            if not isinstance(messages, list) or not all(isinstance(m, str) for m in cast(list[Any], messages)):
                raise Stop(f"check {name} returned {messages!r} on case {case_id}; a check returns a list of failure messages")
            failures[name] = cast(list[str], messages)
        for name, rubric in self.judges.items():
            assert self.ask
            failures[f"{name} (judge)"] = self.ask(name, rubric, case_id, case_input, output)
        return failures


def prepare_suite(prompt: PromptSettings, make_model: MakeModel, make_judge: MakeJudge) -> Suite:
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
    except CheckLoadError as e:
        raise Stop(str(e)) from None
    judges = judges_or_stop(prompt)
    ask = prepare_judge(prompt, providers, has_private, make_judge) if judges else None
    try:
        model = make_model(prompt)
    except MissingKey as e:
        raise Stop(str(e)) from None
    return Suite(requests, checks, judges, ask, model)


def card(case_id: str, case_input: Any, output: Any, failures: dict[str, list[str]]) -> dict[str, Any]:
    """An output as a card: the checks that caught it, and, when any are judges, which ones. A judge's catch is never
    taken as the grader's reason, or agreement would count the judge as agreeing with itself."""
    made: dict[str, Any] = {"case_id": case_id, "input": case_input, "output": output}
    made["caught_by"] = [name.removesuffix(" (judge)") for name, messages in failures.items() if messages]
    judges = [name.removesuffix(" (judge)") for name, messages in failures.items() if messages and name.endswith(" (judge)")]
    return made | ({"judges": judges} if judges else {})


def check_prompt(prompt: PromptSettings, make_model: MakeModel, make_judge: MakeJudge) -> int:
    suite = prepare_suite(prompt, make_model, make_judge)
    print(_calls(len(suite.requests), len(suite.requests) * len(suite.judges)), flush=True)
    results: list[CaseResult] = []
    cards: list[dict[str, Any]] = []
    for case_id, case_input, request in suite.requests:
        try:
            output = suite.model(request).output
        except ModelError as e:
            raise Stop(f"model call failed on case {case_id}: {e}") from None
        failures = suite.score(case_id, case_input, output)
        results.append(CaseResult(case_id, failures))
        cards.append(card(case_id, case_input, output, failures))
    save_deck(prompt.workspace, prompt.dir.name, cards)
    lines, code = report(results, suite.check_names())
    print("\n".join(lines))
    return code


def run_baseline(prompt: PromptSettings, others: list[str], make_model: MakeModel, make_judge: MakeJudge) -> int:
    """The prompt on its production model and each other model, every output in one shuffled deck that never says
    which model wrote a card."""
    others = list(dict.fromkeys(model for model in others if model != prompt.model))
    if not others:
        raise Stop(f"--models needs at least one model besides {prompt.model}")
    suite = prepare_suite(prompt, make_model, make_judge)
    calls = len(suite.requests) * (1 + len(others))
    print(_calls(calls, calls * len(suite.judges)), flush=True)
    models = [prompt.model, *others]
    cards: list[dict[str, Any]] = []
    sources: dict[str, str] = {}  # each card's tag -> the model that wrote it; tags name no case, so this can be committed
    runs: dict[str, list[dict[str, list[str]]]] = {model: [] for model in models}
    tokens = {model: (0, 0) for model in models}
    # Case by case across the models, so a model that rejects the request fails on the first case, not after a
    # whole production run has been paid for.
    for case_id, case_input, request in suite.requests:
        for model in models:
            try:
                result = suite.model({**request, "model": model})
            except ModelError as e:
                raise Stop(f"{model} failed on case {case_id}: {e}") from None
            tokens[model] = (tokens[model][0] + result.input_tokens, tokens[model][1] + result.output_tokens)
            failures = suite.score(case_id, case_input, result.output)
            runs[model].append(failures)
            tag = secrets.token_hex(4)
            cards.append(card(case_id, case_input, result.output, failures) | {"tag": tag})
            sources[tag] = model
    random.shuffle(cards)
    # The run folder first: a deck whose cards can't be traced to their models must never replace the last one.
    deck_id = new_deck_id()
    try:
        save_run(prompt.dir, deck_id, sources, baseline_report(prompt.dir.name, suite.check_names(), runs, tokens))
    except OSError as e:
        raise Stop(f"can't write the baseline run in {prompt.dir / 'runs'}: {e.strerror or e}") from None
    save_deck(prompt.workspace, prompt.dir.name, cards, deck_id)
    return 0


def refresh_baseline_report(prompt: PromptSettings) -> int:
    folder = latest_run(prompt.dir)
    if folder is None:
        raise Stop(f"no baseline run for {prompt.dir.name} yet; run whetstone baseline {prompt.dir.name} --models …")
    report = folder / "report.md"
    deck_id = folder.name.removeprefix("baseline-")
    report.write_text(swipe_section(report.read_text(), load_labels(prompt.dir), deck_id, card_models(folder)))
    return 0


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


def judges_or_stop(prompt: PromptSettings) -> dict[str, Rubric]:
    try:
        return load_judges(prompt.dir)
    except CheckLoadError as e:
        raise Stop(str(e)) from None


def prepare_judge(prompt: PromptSettings, providers: list[str] | None, has_private: bool, make_judge: MakeJudge) -> Ask:
    """Asks one judge about one case's output, giving its failure messages. Everything that can stop it is checked here,
    before any model call."""
    try:
        judged_by = judge_model(prompt.workspace)
    except PromptError as e:
        raise Stop(str(e)) from None
    # Judges see each case's input, so a real-data case goes to them only on a provider the repo already uses.
    if refusal := provider_refusal("openai", providers, has_private):
        raise Stop(refusal)
    try:
        judge = make_judge(prompt.workspace)
    except MissingKey as e:
        raise Stop(str(e)) from None

    def ask(name: str, rubric: Rubric, case_id: str, case_input: Any, output: Any) -> list[str]:
        try:
            return judge_failures(rubric, judge(judge_request(rubric, judged_by, case_input, output)).output)
        except ModelError as e:
            raise Stop(f"judge {name} failed on case {case_id}: {e}") from None
        except JudgeAnswerError as e:
            choices = ", ".join([rubric.passing, *rubric.fail])
            raise Stop(f"judge {name} answered {json.dumps(str(e))} on case {case_id}; expected one of: {choices}") from None

    return ask


def show_agreement(prompt: PromptSettings, make_judge: MakeJudge) -> int:
    judges = judges_or_stop(prompt)
    if not judges:
        print("no judges in checks/")
        return 0
    labels = load_labels(prompt.dir)
    try:
        providers = repo_providers(prompt.workspace)
    except PromptError as e:
        raise Stop(str(e)) from None
    ask = prepare_judge(prompt, providers, any(label["case_id"].startswith("private/") for label in labels), make_judge)
    # Each swiped card is judged once, from the input and output its label kept, however many graders swiped it.
    cards = {label["card_id"]: label for label in labels}
    print(_count(len(cards) * len(judges), "judge call"), flush=True)
    code = 0
    for name, rubric in judges.items():
        verdicts = {card: not ask(name, rubric, label["case_id"], label["input"], label["output"]) for card, label in cards.items()}
        rows = agreement(labels, verdicts, covered_reasons({}, {name: rubric}))
        status, advice = judge_gate(rows)
        print(f"{name}: {status}")
        for grader, row in rows.items():
            print(f"  {grader}: good {_side(row.good)}, bad {_side(row.bad)}")
        print("".join(f"  {line}\n" for line in advice), end="")
        code = 1 if status == "untrusted" else code
    return code


def _calls(generation: int, judging: int) -> str:
    """What a run is about to spend, said before its first call."""
    calls = _count(generation, "generation call")
    return f"{calls} and {_count(judging, 'judge call')}" if judging else calls


def _count(n: int, thing: str) -> str:
    return f"{n} {thing}{'' if n == 1 else 's'}"


def _side(side: Side) -> str:
    return f"{side.agreed}/{side.total} ({round(100 * side.agreed / side.total)}%)" if side.total else "0/0"


def list_reasons(prompt: PromptSettings) -> int:
    judges = judges_or_stop(prompt)
    try:
        code_checks = code_check_reasons(prompt.dir)
    except CheckLoadError as e:
        raise Stop(str(e)) from None
    covered = covered_reasons(code_checks, judges)
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
    # The call keeps the reasons of the swipe it sides with, so the card still counts for that rule's judge.
    sided = [label for label in swiped if label["verdict"] == verdict]
    reasons: list[str] = sided[-1]["reasons"] if sided else []
    swipe: dict[str, Any] = {"grader": grader, "verdict": verdict, "reasons": reasons, "note": note, "settled": True, "at": datetime.now(UTC).isoformat()}
    add_label(prompt.dir, {**swiped[-1], **swipe})
    return 0


def _verdict(label: dict[str, Any]) -> str:
    reasons = f" ({', '.join(label['reasons'])})" if label["reasons"] else ""
    note = f" {json.dumps(label['note'], ensure_ascii=False)}" if label["note"] else ""
    return f"{label['grader']}: {label['verdict']}{reasons}{note}"


def production_model(settings: PromptSettings) -> ModelCall:
    return anthropic_model(load_key(settings.workspace, "GENERATION_API_KEY"))


def production_judge(workspace: Path) -> ModelCall:
    return openai_model(load_key(workspace, "JUDGE_API_KEY"))


def main() -> None:
    sys.exit(run(sys.argv[1:], make_model=production_model, make_judge=production_judge))
