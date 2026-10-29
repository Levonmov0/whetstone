"""The Cloudflare Workers AI wrapper: the only module that calls Workers AI."""

from typing import Any, cast

import httpx2 as httpx

from whetstone.platform.model import ModelCall, ModelError, ModelResult


def cloudflare_model(account_id: str, api_token: str, transport: httpx.BaseTransport | None = None) -> ModelCall:
    # The token goes only in the Authorization header; the account id, which isn't a secret, is in the path.
    client = httpx.Client(
        base_url=f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/",
        headers={"Authorization": f"Bearer {api_token}"},
        timeout=120,
        transport=transport,
    )

    def call(request: dict[str, Any]) -> ModelResult:
        # The URL names the model in full (@cf/cloudflare/clef); Clef's body names it by its selector (clef).
        model = str(request["model"])
        try:
            response = client.post(model, json=request | {"model": model.rsplit("/", 1)[-1]})
        except httpx.HTTPError as e:
            raise ModelError(type(e).__name__) from None
        try:
            body = response.json()
        except ValueError:
            raise ModelError(f"Workers AI {response.status_code}: the reply is not JSON") from None
        envelope = cast(dict[str, Any], body) if isinstance(body, dict) else {}
        if response.status_code != 200 or not envelope.get("success"):
            # Only the status and error codes: the provider's messages are not ours to vouch for, and may echo input.
            errors = envelope.get("errors")
            codes = [str(cast(dict[str, Any], e).get("code")) for e in cast(list[Any], errors) if isinstance(e, dict)] if isinstance(errors, list) else []
            raise ModelError(f"Workers AI {response.status_code}" + (f" (error {', '.join(codes)})" if codes else ""))
        result = envelope.get("result")
        usage = cast(dict[str, Any], result).get("usage") if isinstance(result, dict) else None
        if not isinstance(usage, dict):
            raise ModelError(f"Workers AI {response.status_code}: no usage in the reply")
        tokens = cast(dict[str, Any], usage)
        return ModelResult(output=result, input_tokens=int(tokens.get("input_tokens", 0)), output_tokens=int(tokens.get("output_tokens", 0)))

    return call
