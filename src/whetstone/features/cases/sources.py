"""Real-data sources: one private folder per source, holding its consent record and its cases."""

import json
from datetime import date
from pathlib import Path


def add_source(prompt_dir: Path, name: str, consented_by: str, consented_on: date) -> Path:
    source = prompt_dir / "cases" / "private" / name
    source.mkdir(parents=True)
    # Its own ignore file, so the folder stays out of git whatever the workspace's .gitignore says.
    (source / ".gitignore").write_text("*\n")
    (source / "consent.toml").write_text(f"consented_by = {json.dumps(consented_by)}\nconsented_on = {consented_on.isoformat()}\n")
    return source
