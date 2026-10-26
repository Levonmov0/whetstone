"""Real-data sources: one private folder per source, holding its consent record and its cases."""

import json
from datetime import date
from pathlib import Path


class SourceError(Exception):
    pass


def add_source(prompt_dir: Path, name: str, consented_by: str, consented_on: str) -> Path:
    if name in (".", "..") or "/" in name:
        raise SourceError("source must be a plain folder name")
    if not consented_by.strip():
        raise SourceError("consented-by is required")
    try:
        on = date.fromisoformat(consented_on)
    except ValueError:
        raise SourceError("consented-on must be a date like 2026-10-26") from None
    source = prompt_dir / "cases" / "private" / name
    try:
        source.mkdir(parents=True)
    except FileExistsError:
        raise SourceError(f"source {name} already exists; its consent is in {source / 'consent.toml'}") from None
    # Its own ignore file, so the folder stays out of git whatever the workspace's .gitignore says.
    (source / ".gitignore").write_text("*\n")
    (source / "consent.toml").write_text(f"consented_by = {json.dumps(consented_by.strip())}\nconsented_on = {on.isoformat()}\n")
    return source
