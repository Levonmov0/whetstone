from pathlib import Path


def load_cases(prompt_dir: Path) -> list[tuple[str, str]]:
    """Each case as (id, file contents), in id order. The id is the file name without `.json`."""
    return [(f.stem, f.read_text()) for f in sorted((prompt_dir / "cases").glob("*.json"))]
