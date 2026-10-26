from pathlib import Path


class CaseError(Exception):
    pass


def load_cases(prompt_dir: Path) -> list[tuple[str, str]]:
    """Each case as (id, file contents), in id order. The id is the path under `cases/` without `.json`,
    so a real-data case in a source folder under the gitignored `cases/private/` is `private/<source>/<name>`."""
    cases = prompt_dir / "cases"
    private = [*(cases / "private").glob("*.json"), *(cases / "private").glob("*/*.json")]
    for f in private:
        if not (f.parent / "consent.toml").is_file():
            raise CaseError(f"real-data case {_case_id(cases, f)} has no consent record; run whetstone add-source")
    return sorted((_case_id(cases, f), f.read_text()) for f in [*cases.glob("*.json"), *private])


def _case_id(cases: Path, f: Path) -> str:
    return f.relative_to(cases).with_suffix("").as_posix()
