import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


@pytest.mark.parametrize("module", ["features/checks/canary.py", "features/checks/core.py", "entry/canary.py"])
def test_openai_is_imported_only_in_its_wrapper(module: str, tmp_path: Path) -> None:
    # A copy of the engine with one module importing openai: the contracts must reject it.
    shutil.copytree(ROOT / "src", tmp_path / "src")
    shutil.copy(ROOT / ".importlinter", tmp_path)
    target = tmp_path / "src" / "whetstone" / module
    target.write_text("import openai\n" + (target.read_text() if target.is_file() else ""))

    lint = subprocess.run(["lint-imports"], cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(tmp_path / "src")}, capture_output=True, text=True)

    assert lint.returncode == 1, lint.stdout
    assert "openai" in lint.stdout


@pytest.mark.parametrize("module", ["features/optimize/canary.py", "entry/canary.py"])
def test_gepa_is_imported_only_in_its_wrapper(module: str, tmp_path: Path) -> None:
    shutil.copytree(ROOT / "src", tmp_path / "src")
    shutil.copy(ROOT / ".importlinter", tmp_path)
    target = tmp_path / "src" / "whetstone" / module
    target.write_text("import gepa\n" + (target.read_text() if target.is_file() else ""))

    lint = subprocess.run(["lint-imports"], cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(tmp_path / "src")}, capture_output=True, text=True)

    assert lint.returncode == 1, lint.stdout
    assert "gepa" in lint.stdout
