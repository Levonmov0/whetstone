"""The OpenAI wrapper: the only module that imports the OpenAI SDK."""

from typing import Any

import httpx2 as httpx

from whetstone.platform.model import ModelCall


def openai_model(api_key: str, transport: httpx.BaseTransport | None = None) -> ModelCall:
    raise NotImplementedError
