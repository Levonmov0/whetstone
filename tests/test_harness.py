import time
from pathlib import Path

import pytest

from whetstone.platform.harness import HarnessError, build_request


def test_a_hanging_harness_times_out(tmp_path: Path) -> None:
    started = time.monotonic()

    with pytest.raises(HarnessError, match="harness took longer than 1s"):
        build_request("sleep 10", tmp_path, "{}", timeout=1)

    assert time.monotonic() - started < 5
