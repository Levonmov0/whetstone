"""Pure rules about a prompt's harness request: no I/O, environment or SDKs."""

from typing import Any


def request_problem(request: Any, case_id: str, production_model: str) -> str | None:
    """Why a harness request can't be used, or None when it can."""
    for field in ("model", "messages"):
        if field not in request:
            return f'harness request for case {case_id} is missing "{field}"'
    if request["model"] != production_model:
        return f"harness requests {request['model']} but prompt.toml records production model {production_model}"
    return None
