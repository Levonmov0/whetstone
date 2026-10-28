import tomllib
from datetime import date
from pathlib import Path


class CaseError(Exception):
    pass


def load_cases(prompt_dir: Path, only: str | None = None) -> list[tuple[str, str]]:
    """Each case as (id, file contents), in id order, or only the case `only`. The id is the path under `cases/`
    without `.json`, so a real-data case in a source folder under the gitignored `cases/private/` is
    `private/<source>/<name>`."""
    cases = prompt_dir / "cases"
    private_root = cases / "private"
    private = [f for f in sorted(private_root.rglob("*.json")) if only in (None, _case_id(cases, f))]
    for f in private:
        case_id = _case_id(cases, f)
        source = f.relative_to(private_root).parts[0]
        if len(f.relative_to(private_root).parts) > 2:
            raise CaseError(f"real-data case {case_id} must sit directly in its source folder, cases/private/{source}/")
        consent = f.parent / "consent.toml"
        if f.parent == private_root or not consent.is_file():
            raise CaseError(f"real-data case {case_id} has no consent record; run whetstone add-source")
        _check_consent(consent)
    found = [(_case_id(cases, f), f.read_text()) for f in [*cases.glob("*.json"), *private]]
    return sorted(c for c in found if only in (None, c[0]))


def _check_consent(consent: Path) -> None:
    try:
        record = tomllib.loads(consent.read_text())
    except tomllib.TOMLDecodeError:
        record = {}
    by, on = record.get("consented_by"), record.get("consented_on")
    if not (isinstance(by, str) and by.strip() and isinstance(on, date)):
        raise CaseError(f"{consent} must record consented_by (a name) and consented_on (a date)")


def _case_id(cases: Path, f: Path) -> str:
    return f.relative_to(cases).with_suffix("").as_posix()
