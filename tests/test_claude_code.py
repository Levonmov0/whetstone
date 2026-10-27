import json
import sys
from pathlib import Path

import pytest

from whetstone.platform.claude_code import claude_code_model
from whetstone.platform.model import ModelError


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


REQUEST = {"messages": [{"role": "user", "content": "Improve this prompt."}]}


@pytest.mark.parametrize(
    ("reply", "code", "error"),
    [
        ("not json", 0, "claude printed invalid JSON"),
        ("", 1, "claude exited 1"),
        (json.dumps({"type": "result", "is_error": True, "result": "Not logged in"}), 0, "claude failed: Not logged in"),
    ],
)
def test_a_failed_claude_code_call_is_a_model_error(reply: str, code: int, error: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_claude(tmp_path, monkeypatch, reply, code)

    with pytest.raises(ModelError, match=error):
        claude_code_model()(REQUEST)


def test_no_claude_on_path_is_a_model_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(ModelError, match="Claude Code's claude command was not found; install it, or set rewrite.via = \"api\""):
        claude_code_model()(REQUEST)
