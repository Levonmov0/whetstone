"""A prompt's suite: its vetted requests, checks and judges, shared by every command that runs the prompt."""

import json
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from dataclasses import dataclass
from itertools import repeat
from pathlib import Path
from typing import Any, cast

from whetstone.features.cases.core import provider_refusal
from whetstone.features.cases.load import CaseError, load_cases
from whetstone.features.checks.core import JudgeAnswerError, Rubric, judge_failures, judge_request
from whetstone.features.checks.load import Check, CheckLoadError, load_checks, load_judges
from whetstone.features.workspace.core import request_problem
from whetstone.features.workspace.load import PromptError, PromptSettings, judge_model, prices, repo_providers
from whetstone.platform.config import MissingKey
from whetstone.platform.harness import HarnessError, build_request
from whetstone.platform.model import ModelCall, ModelError

MakeModel = Callable[[PromptSettings], ModelCall]
MakeJudge = Callable[[Path], ModelCall]  # takes the workspace, whose .env holds the judge key
MakeRewrite = Callable[[Path], ModelCall]  # takes the workspace, whose whetstone.toml says how rewrites run
Ask = Callable[[str, Rubric, str, Any, Any], list[str]]  # judge name, rubric, case id, input, output -> failures


class Stop(Exception):
    """A broken setup: the message is printed and the command exits 2."""


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
        if self.judges:
            assert self.ask
            with ThreadPoolExecutor(len(self.judges)) as pool:  # the judges at once: each is a slow model call
                answers = list(pool.map(self.ask, self.judges, self.judges.values(), repeat(case_id), repeat(case_input), repeat(output)))
            failures |= {f"{name} (judge)": answer for name, answer in zip(self.judges, answers)}
        return failures


def prepare_suite(prompt: PromptSettings, make_model: MakeModel, make_judge: MakeJudge) -> Suite:
    if prompt.editable is None:
        raise Stop(f"{prompt.dir.name} has no editable part yet: {prompt.dir / 'editable.txt'} doesn't exist")
    # Every request is built and vetted before the first model call, so a broken harness costs nothing.
    try:
        cases = load_cases(prompt.dir)
    except CaseError as e:
        raise Stop(str(e)) from None
    if not cases:
        raise Stop(f"no cases in {prompt.dir / 'cases'}")
    has_private = any(case_id.startswith("private/") for case_id, _ in cases)
    providers = providers_or_stop(prompt)
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


def providers_or_stop(prompt: PromptSettings) -> list[str] | None:
    try:
        return repo_providers(prompt.workspace)
    except PromptError as e:
        raise Stop(str(e)) from None


def prices_or_stop(prompt: PromptSettings) -> dict[str, tuple[float, float]]:
    try:
        return prices(prompt.workspace)
    except PromptError as e:
        raise Stop(str(e)) from None


def judges_or_stop(prompt: PromptSettings) -> dict[str, Rubric]:
    try:
        return load_judges(prompt.dir)
    except CheckLoadError as e:
        raise Stop(str(e)) from None


def prepare_judge(prompt: PromptSettings, providers: list[str] | None, has_private: bool, make_judge: MakeJudge) -> Ask:
    """Asks one judge about one case's output, giving its failure messages. Everything that can stop it is checked here,
    before any model call."""
    try:
        provider, judged_by = judge_model(prompt.workspace)
    except PromptError as e:
        raise Stop(str(e)) from None
    # Judges see each case's input, so a real-data case goes to them only on a provider the repo already uses.
    if refusal := provider_refusal(provider, providers, has_private):
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

