import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.test_check_cli import make_suite
from whetstone.entry.server import STATIC, make_app
from whetstone.features.workspace.load import load_prompt


def test_a_partial_workspace_theme_still_defines_every_variable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_suite(tmp_path, {"a": "Rest today."})
    # init writes "only the values you found" (skills/init/SKILL.md, step 2)
    (tmp_path / "theme.css").write_text(":root {\n  --ws-accent: #ff5a1f; /* from tokens.css */\n}\n")
    client = TestClient(make_app(load_prompt(tmp_path, "daily"), "t"))

    css = client.get("/theme.css").text

    needed = set(re.findall(r"(--ws-[a-z-]+):", (STATIC / "default.css").read_text()))
    assert needed <= set(re.findall(r"(--ws-[a-z-]+):", css)), f"undefined in the app: {sorted(needed - set(re.findall(r'(--ws-[a-z-]+):', css)))}"
