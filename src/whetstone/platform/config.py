"""Workspace keys: read from the workspace's own `.env`, never from the process environment."""

from pathlib import Path

from dotenv import dotenv_values


class MissingKey(Exception):
    pass


def load_key(workspace: Path, name: str) -> str:
    env_file = workspace / ".env"
    value = dotenv_values(env_file).get(name) if env_file.is_file() else None
    if not value:
        raise MissingKey(f"{name} is not set in {env_file}")
    return value
