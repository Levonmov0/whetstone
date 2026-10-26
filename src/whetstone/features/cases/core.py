"""Pure rules about cases: no I/O, environment or SDKs."""


def provider_refusal(provider: str, repo_providers: list[str] | None, has_private: bool) -> str | None:
    raise NotImplementedError
