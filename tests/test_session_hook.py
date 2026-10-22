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


def copy_plugin(root: Path) -> Path:
    root.mkdir(parents=True)
    for part in ("pyproject.toml", "uv.lock"):
        shutil.copy(REPO / part, root / part)
    for part in ("src", "hooks", "bin"):
        shutil.copytree(REPO / part, root / part, ignore=shutil.ignore_patterns("__pycache__"))
    return root


def test_an_older_plugin_root_keeps_its_own_engine(tmp_path: Path) -> None:
    # After an update, a session still on the old root must not run the new root's code.
    old, new = copy_plugin(tmp_path / "1.0.0"), copy_plugin(tmp_path / "1.1.0")
    cli = new / "src" / "whetstone" / "entry" / "cli.py"
    cli.write_text(cli.read_text().replace('prog="whetstone"', 'prog="whetstone-new"'))
    data = tmp_path / "data"
    base = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    for root in (old, new):
        env = {**base, "CLAUDE_PLUGIN_ROOT": str(root), "CLAUDE_PLUGIN_DATA": str(data)}
        hook = subprocess.run([str(root / "hooks" / "setup-engine.sh")], env=env, capture_output=True, text=True)
        assert hook.returncode == 0, hook.stderr

    old_help = subprocess.run([str(old / "bin" / "whetstone"), "--help"], env=base, capture_output=True, text=True)

    assert old_help.stdout.startswith("usage: whetstone ")
