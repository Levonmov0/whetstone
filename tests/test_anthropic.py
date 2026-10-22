import json
from typing import Any

import httpx2 as httpx
import pytest

from whetstone.platform.anthropic import anthropic_model

REQUEST = {"model": "claude-haiku-5-5", "max_tokens": 50, "messages": [{"role": "user", "content": "Be brief."}]}


def reply(content: list[dict[str, Any]]) -> httpx.MockTransport:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "content": content, "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 12, "output_tokens": 7},
        })
    return httpx.MockTransport(handle)


def test_forced_tool_call_gives_the_tool_input() -> None:
    model = anthropic_model("k", transport=reply([{"type": "tool_use", "id": "t1", "name": "card", "input": {"title": "Rest"}}]))

    result = model(REQUEST)

    assert result.output == {"title": "Rest"}
    assert (result.input_tokens, result.output_tokens) == (12, 7)


def test_text_reply_gives_the_joined_text() -> None:
    model = anthropic_model("k", transport=reply([{"type": "text", "text": "Rest "}, {"type": "text", "text": "today."}]))

    assert model(REQUEST).output == "Rest today."


def test_request_goes_verbatim_to_anthropic_with_the_workspace_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # A Claude Code shell exports its own endpoint and credentials; none of them may reach the call.
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:9/claude-code-proxy")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "shell-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "shell-token")
    seen: list[httpx.Request] = []
    answer = reply([{"type": "text", "text": "ok"}])

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer.handle_request(request)

    anthropic_model("workspace-key", transport=httpx.MockTransport(record))(REQUEST)

    [sent] = seen
    assert str(sent.url) == "https://api.anthropic.com/v1/messages"
    assert sent.headers["x-api-key"] == "workspace-key"
    assert "authorization" not in sent.headers
    assert json.loads(sent.content) == REQUEST
