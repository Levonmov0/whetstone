import json
import queue
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.test_judges_cli import make_judged_suite
from tests.test_matching_cli import swiped, write_labels
from whetstone.features.grading.store import add_label
from whetstone.features.matching.core import swipe_id
from whetstone.features.matching.store import add_event

WHETSTONE = str(Path(sys.executable).parent / "whetstone")


class Follow:
    """`whetstone notes daily --follow` running in the background, its lines read as they come."""

    def __init__(self, workspace: Path) -> None:
        self.process = subprocess.Popen([WHETSTONE, "notes", "daily", "--follow"], cwd=workspace, stdout=subprocess.PIPE, text=True)
        self.lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.lines.put(line)

    def next_swipe(self, timeout: float = 2) -> str:
        return json.loads(self.lines.get(timeout=timeout))["swipe"]

    def nothing_more(self, wait: float = 1.5) -> bool:
        try:
            self.lines.get(timeout=wait)
        except queue.Empty:
            return True
        return False


@pytest.fixture
def follow(tmp_path: Path) -> Iterator[tuple[Path, Follow]]:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    backlog = swiped("c1", note="Says HRV")
    write_labels(prompt / "labels.jsonl", [backlog])
    following = Follow(tmp_path)
    yield prompt, following
    following.process.kill()
    following.process.wait()


def test_follow_prints_the_backlog_then_a_note_saved_after_it_started(follow: tuple[Path, Follow]) -> None:
    prompt, following = follow
    assert following.next_swipe(timeout=10) == swipe_id(swiped("c1", note="Says HRV"))
    later = swiped("c2", note="Too clinical", at="2026-11-20T09:00:00+00:00")

    add_label(prompt, later)

    assert following.next_swipe() == swipe_id(later)


def test_follow_prints_a_note_again_once_the_judge_it_waited_on_is_deleted(tmp_path: Path) -> None:
    prompt = make_judged_suite(tmp_path, {"a": "Rest today."})
    asked = swiped("c1", note="It guessed what I did")
    write_labels(prompt / "labels.jsonl", [asked])
    add_event(prompt, "c1", {"event": "proposed", "id": "m_1", "swipe": swipe_id(asked), "grader": "Hampus", "card_id": "d:c1", "kind": "ask", "reasons": ["assumes"], "why": "Guessing is assuming", "at": "2026-11-20T08:30:00+00:00"})
    following = Follow(tmp_path)
    try:
        assert following.nothing_more(wait=3)

        (prompt / "checks" / "assumes.judge.toml").unlink()

        assert following.next_swipe() == swipe_id(asked)
    finally:
        following.process.kill()
        following.process.wait()
