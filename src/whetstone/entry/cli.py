from collections.abc import Callable
from typing import Any

from whetstone.platform.model import ModelCall


def run(argv: list[str], make_model: Callable[[Any], ModelCall]) -> int:
    return 0
