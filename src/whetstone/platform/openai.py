"""The OpenAI wrapper: the only module that imports the OpenAI SDK."""

import os
from typing import Any, cast

import httpx2 as httpx
import openai
from openai.types.responses import Response

from whetstone.platform.model import ModelCall, ModelError, ModelResult


def openai_model(api_key: str, transport: httpx.BaseTransport | None = None) -> ModelCall:
    # Pinned, like the Anthropic wrapper: the SDK would otherwise take its endpoint, organisation, project, admin key
    # and extra headers from the shell. Empty values stop the environment lookups; Omit() drops each shell header, and
    # our own Authorization makes the SDK drop a shell one.
    shell_headers = [line.split(":", 1)[0].strip() for line in os.environ.get("OPENAI_CUSTOM_HEADERS", "").splitlines() if ":" in line]
    # The empty organisation and project would still go out as empty headers, so those are omitted too.
    omitted = [*shell_headers, "OpenAI-Organization", "OpenAI-Project"]
    headers: dict[str, Any] = {name: openai.Omit() for name in omitted} | {"Authorization": f"Bearer {api_key}"}
    client = openai.OpenAI(
        api_key=api_key,
        admin_api_key="",
        organization="",
        project="",
        base_url="https://api.openai.com/v1",
        default_headers=cast(dict[str, str], headers),  # typed str, but the SDK honours Omit
        http_client=httpx.Client(transport=transport) if transport else None,
    )

    def call(request: dict[str, Any]) -> ModelResult:
        # The body is the judge's verbatim; the SDK can't pick an overload for an untyped dict.
        try:
            reply = cast(Response, client.responses.create(**request))
        except openai.APIError as e:
            # Only the error class and status: the provider's message is not ours to vouch for.
            raise ModelError(f"{type(e).__name__} {getattr(e, 'status_code', '')}".strip()) from None
        usage = reply.usage
        return ModelResult(output=reply.output_text, input_tokens=usage.input_tokens if usage else 0, output_tokens=usage.output_tokens if usage else 0)

    return call
