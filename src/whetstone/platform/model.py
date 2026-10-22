"""The one function type every model call goes through."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelResult:
    output: Any  # a tool's input dict for a forced tool call, else the text
    input_tokens: int
    output_tokens: int


# Takes the provider's request body as the harness built it, verbatim.
ModelCall = Callable[[dict[str, Any]], ModelResult]


class ModelError(Exception):
    """A model call that failed: provider error, rate limit or network. The message never carries a key."""
