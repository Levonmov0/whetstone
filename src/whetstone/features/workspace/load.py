from pathlib import Path


def find_workspace(cwd: Path, explicit: Path | None) -> Path | None:
    for candidate in (explicit,) if explicit else (cwd, cwd / "whetstone"):
        if (candidate / "whetstone.toml").is_file():
            return candidate
    return None


def prompt_names(workspace: Path) -> list[str]:
    return sorted(p.name for p in (workspace / "prompts").iterdir() if p.is_dir())
