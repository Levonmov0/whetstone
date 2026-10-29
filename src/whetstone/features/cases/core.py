"""Pure rules about cases: no I/O, environment or SDKs."""

import json
from typing import Any, cast


def provider_refusal(provider: str, repo_providers: list[str] | None, has_private: bool) -> str | None:
    """Why real-data cases can't be sent to this provider, or None when they can (or there are none).
    Every model call that may carry a real-data case asks this first."""
    if not has_private:
        return None
    if not repo_providers:
        return "whetstone.toml has no repo_providers; real-data cases need it"
    if provider not in repo_providers:
        return f"real-data cases go only to providers this repo already uses ({', '.join(repo_providers)}); {provider} is not one"
    return None


ABOUT = "_about"


def split_about(case: Any) -> tuple[Any, Any]:
    """A case without its `_about`, and the `_about` (None when it has none): a plain-language summary of what the case
    tests, for the grader's card only. No harness, model or judge ever gets it."""
    if not isinstance(case, dict) or ABOUT not in case:
        return cast(Any, case), None
    fields = cast(dict[str, Any], case)
    return {k: v for k, v in fields.items() if k != ABOUT}, fields[ABOUT]


def without_about(case_json: str) -> str:
    """A case file as its harness gets it: without its `_about`, and byte for byte when it has none."""
    try:
        case = json.loads(case_json)
    except ValueError:
        return case_json  # the harness reports it
    rest, about = split_about(case)
    return case_json if about is None else json.dumps(rest, ensure_ascii=False)
