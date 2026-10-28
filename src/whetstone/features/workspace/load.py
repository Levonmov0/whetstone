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
    editable: str | None  # editable.txt, byte for byte; None until init writes it. check needs it, verify-harness does not
    reasons: list[str]  # the swipe app's reason chips


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
    reasons = raw.get("reasons", [])
    if not (isinstance(reasons, list) and all(isinstance(r, str) for r in cast(list[Any], reasons))):
        raise PromptError(f"{settings_file}: reasons must be a list of text")
    placeholders = raw.get("placeholders", {})
    if not (isinstance(placeholders, dict) and all(isinstance(v, str) for v in cast(dict[str, Any], placeholders).values())):
        raise PromptError(f"{settings_file}: [placeholders] must map each placeholder to its text")
    if raw.get("apply", "exact") not in ("exact", "code-edit"):
        raise PromptError(f'{settings_file}: apply must be "exact" or "code-edit"')
    if raw["provider"] != "anthropic":
        raise PromptError(f'{settings_file}: provider "{raw["provider"]}" is not supported yet; Whetstone calls anthropic only')
    return PromptSettings(
        workspace=workspace,
        dir=prompt_dir,
        harness=raw["harness"],
        provider=raw["provider"],
        model=raw["model"],
        editable=(prompt_dir / "editable.txt").read_text() if (prompt_dir / "editable.txt").is_file() else None,
        reasons=cast(list[str], reasons),
    )


def _workspace_settings(workspace: Path) -> dict[str, Any]:
    settings_file = workspace / "whetstone.toml"
    try:
        return tomllib.loads(settings_file.read_text())
    except tomllib.TOMLDecodeError as e:
        raise PromptError(f"{settings_file}: invalid TOML: {e}") from None


def phone_access(workspace: Path) -> str:
    """How phones reach the swipe server: "lan" (the default) or "tailscale"."""
    phone = _workspace_settings(workspace).get("phone", {})
    access = cast(dict[str, Any], phone).get("access", "lan") if isinstance(phone, dict) else None
    if access not in ("lan", "tailscale"):
        raise PromptError(f'{workspace / "whetstone.toml"}: phone.access must be "lan" or "tailscale"')
    return cast(str, access)


def repo_providers(workspace: Path) -> list[str] | None:
    """The model providers this repo already uses, as init recorded them; None when not recorded."""
    settings_file = workspace / "whetstone.toml"
    providers = _workspace_settings(workspace).get("repo_providers")
    if providers is not None and not (isinstance(providers, list) and all(isinstance(p, str) for p in cast(list[Any], providers))):
        raise PromptError(f"{settings_file}: repo_providers must be a list of provider names")
    return cast(list[str] | None, providers)


def judge_model(workspace: Path) -> tuple[str, str]:
    """The provider and model judges run on, from `[models] judge` in whetstone.toml. OpenAI is the only provider so far;
    another backend (a cheap classifier) adds its name here."""
    models = _workspace_settings(workspace).get("models")
    judge = cast(dict[str, Any], models).get("judge") if isinstance(models, dict) else None
    settings = cast(dict[str, Any], judge) if isinstance(judge, dict) else {}
    if not (settings.get("provider") == "openai" and isinstance(settings.get("model"), str)):
        raise PromptError(f'{workspace / "whetstone.toml"}: [models] judge needs provider = "openai" and a model')
    return cast(str, settings["provider"]), cast(str, settings["model"])


def prices(workspace: Path) -> dict[str, tuple[float, float]]:
    """Each model's dollars per million input and output tokens, from `[prices]` in whetstone.toml."""
    table = _workspace_settings(workspace).get("prices", {})
    entries = cast(dict[str, Any], table) if isinstance(table, dict) else None
    valid = entries is not None and all(
        isinstance(v, list) and len(cast(list[Any], v)) == 2 and all(isinstance(n, int | float) for n in cast(list[Any], v)) for v in entries.values()
    )
    if entries is None or not valid:
        raise PromptError(f"{workspace / 'whetstone.toml'}: [prices] maps each model to [input, output] dollars per million tokens")
    return {model: (float(v[0]), float(v[1])) for model, v in entries.items()}


def rewrite_settings(workspace: Path) -> tuple[str, str | None]:
    """How rewrites run, from `[models] rewrite` in whetstone.toml: "claude-code" (the default) or "api", and the
    model to ask for, when one is named. The API needs one."""
    settings_file = workspace / "whetstone.toml"
    models = _workspace_settings(workspace).get("models")
    rewrite: Any = cast(dict[str, Any], models).get("rewrite", {}) if isinstance(models, dict) else {}
    settings = cast(dict[str, Any], rewrite) if isinstance(rewrite, dict) else {}
    via, model = settings.get("via", "claude-code"), settings.get("model")
    if via not in ("claude-code", "api"):
        raise PromptError(f'{settings_file}: [models] rewrite.via must be "claude-code" or "api"')
    if model is not None and not isinstance(model, str):
        raise PromptError(f"{settings_file}: [models] rewrite.model must be a model name")
    if via == "api" and model is None:
        raise PromptError(f'{settings_file}: [models] rewrite.via = "api" needs a model')
    return cast(str, via), model
