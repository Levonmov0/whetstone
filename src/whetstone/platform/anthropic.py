import httpx2 as httpx

from whetstone.platform.model import ModelCall


def anthropic_model(api_key: str, transport: httpx.BaseTransport | None = None) -> ModelCall:
    raise NotImplementedError
