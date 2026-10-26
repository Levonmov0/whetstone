import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


def find_workspace(cwd: Path, explicit: Path | None) -> Path | None:
    for candidate in (explicit,) if explicit else (cwd, cwd / "whetstone"):
        if (candidate / "whetstone.toml").is_file():
            return candidate
    return None


def prompt_names(workspace: Path) -> list[str]:
    prompts = workspace / "prompts"
    return sorted(p.name for p in prompts.iterdir() if p.is_dir()) if prompts.is_dir() else []


class PromptError(Exception):
    """A prompt folder whose settings can't be used."""


@dataclass(frozen=True)
class PromptSettings:
    workspace: Path
    dir: Path
    harness: str
    provider: str
    model: str
    editable: str | None  # None until init marks it; check needs it, verify-harness does not


def load_prompt(workspace: Path, name: str) -> PromptSettings:
    prompt_dir = workspace / "prompts" / name
    settings_file = prompt_dir / "prompt.toml"
    try:
        raw = tomllib.loads(settings_file.read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise PromptError(f"{settings_file}: invalid TOML: {e}") from None
    for key in ("harness", "provider", "model"):
        if not isinstance(raw.get(key), str):
            raise PromptError(f'{settings_file}: missing "{key}"')
    if raw["provider"] != "anthropic":
        raise PromptError(f'{settings_file}: provider "{raw["provider"]}" is not supported yet; Whetstone calls anthropic only')
    return PromptSettings(
        workspace=workspace, dir=prompt_dir, harness=raw["harness"], provider=raw["provider"], model=raw["model"], editable=raw.get("editable")
    )


def repo_providers(workspace: Path) -> list[str] | None:
    """The model providers this repo already uses, as init recorded them; None when not recorded."""
    settings_file = workspace / "whetstone.toml"
    try:
        providers = tomllib.loads(settings_file.read_text()).get("repo_providers")
    except tomllib.TOMLDecodeError as e:
        raise PromptError(f"{settings_file}: invalid TOML: {e}") from None
    if providers is not None and not (isinstance(providers, list) and all(isinstance(p, str) for p in cast(list[Any], providers))):
        raise PromptError(f"{settings_file}: repo_providers must be a list of provider names")
    return cast(list[str] | None, providers)
