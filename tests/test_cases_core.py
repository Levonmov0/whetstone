import pytest

from whetstone.features.cases.core import provider_refusal


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
