import importlib.util
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from whetstone.features.checks.core import Rubric

Check = Callable[[Any], Any]


class CheckLoadError(Exception):
    pass


def load_checks(prompt_dir: Path) -> dict[str, Check]:
    """Each `checks/<name>.py` module's `check(output)`, which returns failure messages (empty means pass)."""
    checks: dict[str, Check] = {}
    for path in sorted((prompt_dir / "checks").glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"whetstone_check_{path.stem}", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:  # the workspace's own code; any failure means the check can't run
            raise CheckLoadError(f"check {path.stem} failed to load: {type(e).__name__}: {e}") from None
        if not callable(getattr(module, "check", None)):
            raise CheckLoadError(f'check {path.stem} failed to load: {path} has no "check" function')
        checks[path.stem] = module.check
    return checks


def load_judges(prompt_dir: Path) -> dict[str, Rubric]:
    """Each `checks/<name>.judge.toml` rubric."""
    judges: dict[str, Rubric] = {}
    for path in sorted((prompt_dir / "checks").glob("*.judge.toml")):
        name = path.name.removesuffix(".judge.toml")
        if path.with_name(f"{name}.py").is_file():
            raise CheckLoadError(f"check {name} is both {name}.py and {name}.judge.toml")
        judges[name] = _rubric(path)
    return judges


def _rubric(path: Path) -> Rubric:
    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise CheckLoadError(f"{path}: invalid TOML: {e}") from None
    for key in ("question", "pass"):
        if not isinstance(raw.get(key), str):
            raise CheckLoadError(f'{path}: missing "{key}"')
    fail = raw.get("fail")
    if not isinstance(fail, dict) or not fail:
        raise CheckLoadError(f"{path}: needs at least one failing answer under [fail]")
    if not all(isinstance(reason, str) for reason in cast(dict[str, Any], fail).values()):
        raise CheckLoadError(f"{path}: [fail] maps each failing answer to its reason text")
    if raw["pass"] in fail:
        raise CheckLoadError(f"{path}: \"{raw['pass']}\" can't be both the passing answer and a failing one")
    guide = raw.get("guide", "")
    if not isinstance(guide, str):
        raise CheckLoadError(f"{path}: guide must be text")
    reasons = raw.get("reasons", [])
    if not (isinstance(reasons, list) and all(isinstance(r, str) for r in cast(list[Any], reasons))):
        raise CheckLoadError(f"{path}: reasons must be a list of text")
    return Rubric(raw["question"], guide, raw["pass"], cast(dict[str, str], fail), cast(list[str], reasons))


def code_check_names(prompt_dir: Path) -> list[str]:
    """The code checks' names, without running their code."""
    return [path.stem for path in sorted((prompt_dir / "checks").glob("*.py"))]
