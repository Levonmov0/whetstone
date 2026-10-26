from whetstone.features.cases.core import provider_refusal


def test_an_empty_provider_list_names_repo_providers() -> None:
    # spec item 8: (anthropic, [], True) -> refusal naming repo_providers missing in whetstone.toml
    refusal = provider_refusal("anthropic", [], True)

    assert refusal is not None and "repo_providers" in refusal and "()" not in refusal, refusal
