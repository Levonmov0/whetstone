import tomllib
from dataclasses import dataclass
from pathlib import Path


def find_workspace(cwd: Path, explicit: Path | None) -> Path | None:
    for candidate in (explicit,) if explicit else (cwd, cwd / "whetstone"):
        if (candidate / "whetstone.toml").is_file():
            return candidate
    return None


def prompt_names(workspace: Path) -> list[str]:
    return sorted(p.name for p in (workspace / "prompts").iterdir() if p.is_dir())


@dataclass(frozen=True)
class PromptSettings:
    workspace: Path
    dir: Path
    harness: str
    model: str
    editable: str


def load_prompt(workspace: Path, name: str) -> PromptSettings:
    prompt_dir = workspace / "prompts" / name
    raw = tomllib.loads((prompt_dir / "prompt.toml").read_text())
    return PromptSettings(workspace=workspace, dir=prompt_dir, harness=raw["harness"], model=raw["model"], editable=raw["editable"])
