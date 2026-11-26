#!/bin/sh
# SessionStart: build Whetstone's Python engine in the plugin's data folder, then
# point bin/whetstone at it. Claude's Bash tool gets bin/ on PATH but not the
# plugin variables, so the link in the plugin root is how bin finds the engine.
# One venv per plugin root: the data folder outlives updates, and a session still
# on an older root must keep running that root's code.
# ponytail: venvs of removed roots stay in the data folder; prune them if it grows.
set -eu
root_id="$(printf %s "$CLAUDE_PLUGIN_ROOT" | cksum | cut -d' ' -f1)"
venv="$CLAUDE_PLUGIN_DATA/venv-$root_id"
UV_PROJECT_ENVIRONMENT="$venv" uv sync --frozen --no-dev --quiet --project "$CLAUDE_PLUGIN_ROOT"
ln -sfn "$venv" "$CLAUDE_PLUGIN_ROOT/.engine"
