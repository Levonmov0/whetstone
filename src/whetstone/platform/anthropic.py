"""The Anthropic wrapper: the only module that imports the Anthropic SDK."""

from typing import Any, cast

import anthropic
import httpx2 as httpx

from whetstone.platform.model import ModelCall, ModelError, ModelResult


def anthropic_model(api_key: str, transport: httpx.BaseTransport | None = None) -> ModelCall:
    # Pinned: a Claude Code shell exports ANTHROPIC_BASE_URL and its own credentials.
    client = anthropic.Anthropic(
        api_key=api_key, auth_token=None, base_url="https://api.anthropic.com", http_client=httpx.Client(transport=transport) if transport else None
    )

    def call(request: dict[str, Any]) -> ModelResult:
        # The body is the harness's verbatim; the SDK can't pick an overload for an untyped dict.
        try:
            reply = cast(anthropic.types.Message, client.messages.create(**request))
        except anthropic.APIError as e:
            # Only the error class and status: the provider's message is not ours to vouch for.
            raise ModelError(f"{type(e).__name__} {getattr(e, 'status_code', '')}".strip()) from None
        tool_inputs = [block.input for block in reply.content if block.type == "tool_use"]
        output = tool_inputs[0] if tool_inputs else "".join(block.text for block in reply.content if block.type == "text")
        return ModelResult(output=output, input_tokens=reply.usage.input_tokens, output_tokens=reply.usage.output_tokens)

    return call
