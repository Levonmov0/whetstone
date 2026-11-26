"""A case's judges are asked at once, not one after another."""

import threading
from typing import Any

from whetstone.entry.suite import Suite
from whetstone.features.checks.core import Rubric


def test_judges_run_at_once() -> None:
    # Each judge waits for the other two; asked one after another, the first would time out.
    barrier = threading.Barrier(3, timeout=5)

    def ask(name: str, rubric: Rubric, case_id: str, case_input: Any, output: Any) -> list[str]:
        barrier.wait()
        return [] if name != "b" else ["b failed"]

    rubric = Rubric("q", "g", "yes", {"no": "bad"}, [])
    suite = Suite([], {}, {"a": rubric, "b": rubric, "c": rubric}, ask, lambda request: None)  # pyright: ignore[reportArgumentType]

    assert suite.score("case", {}, "out") == {"a (judge)": [], "b (judge)": ["b failed"], "c (judge)": []}
