import json
import sys
from pathlib import Path

import pytest

from whetstone.platform.claude_code import claude_code_model


def fake_claude(folder: Path, monkeypatch: pytest.MonkeyPatch, reply: str, code: int = 0) -> Path:
    """A `claude` on PATH that records how it was called and prints `reply`."""
    record = folder / "called.json"
    script = folder / "bin" / "claude"
    script.parent.mkdir()
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'cwd': os.getcwd(), 'stdin': sys.stdin.read()}}, open({str(record)!r}, 'w'))\n"
        f"print({reply!r})\n"
        f"sys.exit({code})\n"
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", str(script.parent))
    return record


REPLY = json.dumps(
    {
        "type": "result",
        "is_error": False,
        "result": "```\nKeep it short.\n```",
        "total_cost_usd": 0.05,
        "usage": {"input_tokens": 2, "cache_creation_input_tokens": 500, "cache_read_input_tokens": 300, "output_tokens": 40},
    }
)


def test_a_rewrite_goes_through_claude_code_headless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = fake_claude(tmp_path, monkeypatch, REPLY)
    rewrite = claude_code_model()

    result = rewrite({"model": "claude-sonnet-5-5", "max_tokens": 8000, "messages": [{"role": "user", "content": "Improve this prompt."}]})

    called = json.loads(record.read_text())
    assert called["argv"] == [
        "-p", "--output-format", "json", "--tools", "", "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config",
        "--model", "claude-sonnet-5-5",
    ]  # fmt: skip
    assert called["stdin"] == "Improve this prompt."
    assert not Path(called["cwd"]).exists()  # an empty temp folder, gone afterwards: no repo files or CLAUDE.md to read
    assert (result.output, result.input_tokens, result.output_tokens, result.cost_usd) == ("```\nKeep it short.\n```", 802, 40, 0.05)


def test_without_a_model_claude_code_uses_its_own_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = fake_claude(tmp_path, monkeypatch, REPLY)

    claude_code_model()({"max_tokens": 8000, "messages": [{"role": "user", "content": "Improve this prompt."}]})

    assert "--model" not in json.loads(record.read_text())["argv"]
