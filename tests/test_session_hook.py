import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_session_hook_builds_the_engine_and_bin_runs_it(tmp_path: Path) -> None:
    # A copy of the plugin, so the hook's writes never touch this checkout.
    root = tmp_path / "plugin"
    root.mkdir()
    for part in ("pyproject.toml", "uv.lock"):
        shutil.copy(REPO / part, root / part)
    for part in ("src", "hooks", "bin"):
        shutil.copytree(REPO / part, root / part, ignore=shutil.ignore_patterns("__pycache__"))
    data = tmp_path / "data"
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(root), "CLAUDE_PLUGIN_DATA": str(data)}
    env.pop("VIRTUAL_ENV", None)

    hook = subprocess.run([str(root / "hooks" / "setup-engine.sh")], env=env, capture_output=True, text=True)
    assert hook.returncode == 0, hook.stderr
    assert (data / "venv").is_dir()

    # Claude's Bash tool gets bin/ on PATH but not the plugin variables.
    bare = {k: v for k, v in env.items() if not k.startswith("CLAUDE_PLUGIN_")}
    help_run = subprocess.run([str(root / "bin" / "whetstone"), "--help"], env=bare, capture_output=True, text=True)
    assert help_run.returncode == 0, help_run.stderr
    assert "check" in help_run.stdout
