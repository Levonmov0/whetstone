"""Pure rules about cases: no I/O, environment or SDKs."""


def provider_refusal(provider: str, repo_providers: list[str] | None, has_private: bool) -> str | None:
    """Why real-data cases can't be sent to this provider, or None when they can (or there are none).
    Every model call that may carry a real-data case asks this first."""
    if not has_private:
        return None
    if not repo_providers:
        return "whetstone.toml has no repo_providers; real-data cases need it"
    if provider not in repo_providers:
        return f"real-data cases go only to providers this repo already uses ({', '.join(repo_providers)}); {provider} is not one"
    return None
