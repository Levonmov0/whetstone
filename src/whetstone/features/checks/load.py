import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Any

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
