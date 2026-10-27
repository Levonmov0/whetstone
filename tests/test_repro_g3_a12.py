import httpx2 as httpx

from tests.test_openai import REQUEST, reply
from whetstone.platform.openai import openai_model


def test_no_empty_organization_or_project_header_is_sent() -> None:
    seen: list[httpx.Request] = []

    openai_model("workspace-key", transport=reply(seen=seen))(REQUEST)

    [sent] = seen
    assert {name: sent.headers[name] for name in ("openai-organization", "openai-project") if name in sent.headers} == {}
