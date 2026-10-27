"""Claude Code's headless mode as a model call: the default way rewrites run, on the user's own Claude login."""

import json
import shutil
import subprocess
import tempfile
from typing import Any

from whetstone.platform.model import ModelCall, ModelError, ModelResult


def claude_code_model() -> ModelCall:
    def call(request: dict[str, Any]) -> ModelResult:
        claude = shutil.which("claude")
        if claude is None:
            raise ModelError("Claude Code's claude command was not found; install it, or set rewrite.via = \"api\"")
        # No tools, settings, plugins or MCP servers, in an empty folder: the rewrite sees only the prompt it is given.
        argv = [claude, "-p", "--output-format", "json", "--tools", "", "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config"]
        if "model" in request:
            argv += ["--model", request["model"]]
        prompt = "\n\n".join(message["content"] for message in request["messages"])
        with tempfile.TemporaryDirectory() as empty:
            result = subprocess.run(argv, input=prompt, capture_output=True, text=True, cwd=empty)
        if result.returncode != 0:
            raise ModelError(f"claude exited {result.returncode}: {result.stderr.strip()}")
        try:
            reply = json.loads(result.stdout)
        except ValueError:
            raise ModelError("claude printed invalid JSON") from None
        if reply["is_error"]:
            raise ModelError(f"claude failed: {reply['result']}")
        usage = reply["usage"]
        tokens_in = usage["input_tokens"] + usage["cache_creation_input_tokens"] + usage["cache_read_input_tokens"]
        return ModelResult(output=reply["result"], input_tokens=tokens_in, output_tokens=usage["output_tokens"], cost_usd=reply["total_cost_usd"])

    return call
