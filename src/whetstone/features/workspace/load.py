import tomllib
from dataclasses import dataclass
from pathlib import Path


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
