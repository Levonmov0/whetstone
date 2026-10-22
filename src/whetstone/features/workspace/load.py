from pathlib import Path


def find_workspace(cwd: Path) -> Path | None:
    for candidate in (cwd, cwd / "whetstone"):
        if (candidate / "whetstone.toml").is_file():
            return candidate
    return None
