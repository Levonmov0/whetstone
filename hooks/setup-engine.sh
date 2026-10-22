#!/bin/sh
# SessionStart: build Whetstone's Python engine in the plugin's data folder, then
# point bin/whetstone at it. Claude's Bash tool gets bin/ on PATH but not the
# plugin variables, so the link in the plugin root is how bin finds the engine.
set -eu
venv="$CLAUDE_PLUGIN_DATA/venv"
UV_PROJECT_ENVIRONMENT="$venv" uv sync --frozen --no-dev --quiet --project "$CLAUDE_PLUGIN_ROOT"
ln -sfn "$venv" "$CLAUDE_PLUGIN_ROOT/.engine"
