from typing import Any

import httpx2 as httpx

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
