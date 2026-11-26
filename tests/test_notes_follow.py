import fcntl
import json
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.test_judges_cli import make_judged_suite
from tests.test_matching_cli import swiped, write_labels
from whetstone.features.grading.store import add_label, load_labels
from whetstone.features.matching.core import swipe_id
from whetstone.features.matching.store import add_event, load_events

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


def test_a_check_that_fails_to_load_mid_edit_does_not_end_the_follow(follow: tuple[Path, Follow]) -> None:
    prompt, following = follow
    following.next_swipe(timeout=10)
    (prompt / "checks" / "half_written.py").write_text("REASONS = [\n")
    assert following.nothing_more()
    later = swiped("c2", note="Too clinical", at="2026-11-20T09:00:00+00:00")

    add_label(prompt, later)

    assert following.next_swipe() == swipe_id(later)


def test_follow_prints_a_note_it_printed_again_once_its_match_goes_stale(follow: tuple[Path, Follow]) -> None:
    prompt, following = follow
    backlog = swiped("c1", note="Says HRV")
    assert following.next_swipe(timeout=10) == swipe_id(backlog)
    add_event(prompt, "c1", {"event": "proposed", "id": "m_1", "swipe": swipe_id(backlog), "grader": "Hampus", "card_id": "d:c1", "kind": "ask", "reasons": ["assumes"], "why": "Guessing is assuming", "at": "2026-11-20T08:30:00+00:00"})
    assert following.nothing_more()

    (prompt / "checks" / "assumes.judge.toml").unlink()

    assert following.next_swipe() == swipe_id(backlog)


@pytest.mark.parametrize("name, load", [("labels.jsonl", load_labels), ("matches.jsonl", load_events)])
def test_a_read_waits_for_a_line_another_process_is_still_writing(tmp_path: Path, name: str, load: Callable[[Path], list[dict[str, Any]]]) -> None:
    line = json.dumps({"note": "x" * 20_000}) + "\n"
    read: list[list[dict[str, Any]] | BaseException] = []
    with (tmp_path / name).open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)  # as add_label and add_event hold it, a long line going out in several writes
        f.write(line[:8192])
        f.flush()
        reader = threading.Thread(target=lambda: read.append(_try(lambda: load(tmp_path))))
        reader.start()
        time.sleep(0.3)
        f.write(line[8192:])
    reader.join(timeout=5)

    assert read == [[{"note": "x" * 20_000}]]


def _try(call: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]] | BaseException:
    try:
        return call()
    except Exception as e:
        return e
