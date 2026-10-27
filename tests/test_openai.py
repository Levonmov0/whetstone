import json
from typing import Any

import httpx2 as httpx
import pytest

from whetstone.platform.model import ModelError
from whetstone.platform.openai import openai_model

REQUEST = {"model": "gpt-5.5", "instructions": "Check one rule.", "input": "Question: ?"}


def reply(status: int = 200, body: dict[str, Any] | None = None, seen: list[httpx.Request] | None = None) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body or {
            "id": "resp_1", "object": "response", "created_at": 1, "status": "completed", "model": "gpt-5.5",
            "output": [{"type": "message", "id": "msg_1", "status": "completed", "role": "assistant",
                        "content": [{"type": "output_text", "text": '{"answer": "no"}', "annotations": []}]}],
            "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
            "usage": {"input_tokens": 30, "output_tokens": 4, "total_tokens": 34,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
        })
    return httpx.MockTransport(handle)


def test_reply_gives_the_output_text_and_tokens() -> None:
    result = openai_model("k", transport=reply())(REQUEST)

    assert result.output == '{"answer": "no"}'
    assert (result.input_tokens, result.output_tokens) == (30, 4)


def test_request_goes_verbatim_to_openai_with_the_workspace_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # A shell may export its own endpoint, credentials and headers; none of them may reach the call.
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:9/proxy")
    monkeypatch.setenv("OPENAI_API_KEY", "shell-key")
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "shell-admin")
    monkeypatch.setenv("OPENAI_ORG_ID", "shell-org")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "shell-project")
    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", "Authorization: Bearer shell-token\nX-Shell: yes")
    seen: list[httpx.Request] = []

    openai_model("workspace-key", transport=reply(seen=seen))(REQUEST)

    [sent] = seen
    assert str(sent.url) == "https://api.openai.com/v1/responses"
    assert sent.headers["authorization"] == "Bearer workspace-key"
    for leaked in ("shell-key", "shell-admin", "shell-org", "shell-project", "shell-token", "X-Shell"):
        assert leaked.lower() not in str(sent.headers).lower()
    assert json.loads(sent.content) == REQUEST


def test_provider_error_names_only_its_class_and_status() -> None:
    model = openai_model("k", transport=reply(500, {"error": {"message": "secret detail k", "type": "server_error"}}))

    with pytest.raises(ModelError) as raised:
        model(REQUEST)

    assert str(raised.value) == "InternalServerError 500"
