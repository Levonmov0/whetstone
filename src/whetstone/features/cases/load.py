from pathlib import Path


def load_cases(prompt_dir: Path) -> list[tuple[str, str]]:
    """Each case as (id, file contents), in id order. The id is the path under `cases/` without `.json`,
    so a real-data case in the gitignored `cases/private/` is `private/<name>`."""
    cases = prompt_dir / "cases"
    files = [*cases.glob("*.json"), *(cases / "private").glob("*.json")]
    return sorted((f.relative_to(cases).with_suffix("").as_posix(), f.read_text()) for f in files)
