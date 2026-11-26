import json
from typing import Any

import httpx2 as httpx
import pytest

from whetstone.platform.cloudflare import cloudflare_model
from whetstone.platform.model import ModelError

ACCOUNT = "0123456789abcdef0123456789abcdef"
REQUEST = {"model": "@cf/cloudflare/clef", "state": {"output": "Rest today."}, "questions": {"verdict": {"type": "choice", "instructions": "?", "criteria": {"no": None, "yes": "assumes"}}}}
RESULT = {
    "model": "clef",
    "answers": {"verdict": {"type": "choice", "choice": "no", "probabilities": {"no": 0.9, "yes": 0.1}, "confidence": 0.8}},
    "usage": {"input_tokens": 120, "output_tokens": 0},
}


def reply(status: int = 200, body: dict[str, Any] | None = None, seen: list[httpx.Request] | None = None) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body or {"result": RESULT, "success": True, "errors": [], "messages": []})
    return httpx.MockTransport(handle)


def test_reply_gives_the_answers_and_tokens() -> None:
    result = cloudflare_model(ACCOUNT, "tok", transport=reply())(REQUEST)

    assert result.output == RESULT
    assert (result.input_tokens, result.output_tokens) == (120, 0)


def test_request_goes_to_the_account_with_the_token_in_a_header_only() -> None:
    seen: list[httpx.Request] = []

    cloudflare_model(ACCOUNT, "secret-token", transport=reply(seen=seen))(REQUEST)

    [sent] = seen
    assert str(sent.url) == f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/ai/run/@cf/cloudflare/clef"
    assert sent.headers["authorization"] == "Bearer secret-token"
    assert "secret-token" not in str(sent.url)
    # The URL names the model in full; the body names it as Clef's own selector.
    assert json.loads(sent.content) == REQUEST | {"model": "clef"}


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (401, {"success": False, "errors": [{"code": 10000, "message": "Authentication error, token secret-token"}], "result": None}, "Workers AI 401 (error 10000)"),
        (200, {"success": False, "errors": [{"code": 5006, "message": "bad input"}], "result": None}, "Workers AI 200 (error 5006)"),
        (200, {"success": True, "errors": [], "result": {"answers": {}}}, "Workers AI 200: no usage in the reply"),
    ],
)
def test_provider_error_names_only_its_status_and_codes(status: int, body: dict[str, Any], message: str) -> None:
    with pytest.raises(ModelError) as e:
        cloudflare_model(ACCOUNT, "secret-token", transport=reply(status, body))(REQUEST)

    assert str(e.value) == message


def test_a_network_failure_is_a_model_error() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(ModelError, match="ConnectError"):
        cloudflare_model(ACCOUNT, "tok", transport=httpx.MockTransport(fail))(REQUEST)
