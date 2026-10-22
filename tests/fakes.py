"""Stand-ins for the two outside systems: the model provider and the harness."""

from collections.abc import Callable
from typing import Any

from whetstone.platform.model import ModelCall, ModelResult


class FakeModel:
    """Answers each request with `answer(request)` and records every request it got."""

    def __init__(self, answer: Callable[[dict[str, Any]], Any]) -> None:
        self.answer = answer
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: dict[str, Any]) -> ModelResult:
        self.requests.append(request)
        return ModelResult(output=self.answer(request), input_tokens=10, output_tokens=5)


def unused_model(_settings: Any) -> ModelCall:
    raise AssertionError("no model call was expected")
