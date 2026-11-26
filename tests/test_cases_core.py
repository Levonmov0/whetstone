import json

import pytest

from whetstone.features.cases.core import provider_refusal, split_about, without_about


@pytest.mark.parametrize(
    ("provider", "repo_providers", "has_private", "refusal"),
    [
        ("anthropic", ["anthropic"], True, None),
        ("openai", ["anthropic"], True, "real-data cases go only to providers this repo already uses (anthropic); openai is not one"),
        ("openai", ["anthropic"], False, None),
        ("anthropic", None, True, "whetstone.toml has no repo_providers; real-data cases need it"),
        ("anthropic", None, False, None),
    ],
)
def test_provider_refusal(provider: str, repo_providers: list[str] | None, has_private: bool, refusal: str | None) -> None:
    assert provider_refusal(provider, repo_providers, has_private) == refusal


def test_a_case_summary_is_split_from_what_the_harness_gets() -> None:
    case = {"journal": "Can't wait to wake up.", "_about": "Tests the open thread."}

    assert split_about(case) == ({"journal": "Can't wait to wake up."}, "Tests the open thread.")
    assert json.loads(without_about(json.dumps(case))) == {"journal": "Can't wait to wake up."}


@pytest.mark.parametrize("case_json", ['{"journal": "Slept."}', '["not", "an object"]', "not json"])
def test_a_case_without_a_summary_reaches_the_harness_byte_for_byte(case_json: str) -> None:
    assert without_about(case_json) == case_json
