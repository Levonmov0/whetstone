# Whetstone

Claude Code plugin and Python CLI for test-driven prompt optimization.

## Commands

- Single Python test: `uv run pytest tests/test_matching_core.py -k <name>`
- Single JS app test: `node --test tests/app/matches.test.mjs`
- Full check (= CI): `make check` (`pyright`, `lint-imports`, `pytest -q`, `apptest`)
- Live model smoke test (costs money; excluded from `make check`): `make smoke`

## Conventions and boundaries

- Keep `src/whetstone/features/*/core.py` pure (no I/O, `pathlib`, `os`, `subprocess`, or SDKs), keep features independent, and keep SDK imports in `src/whetstone/platform/` (enforced by `.importlinter`).
- Ask before running `make smoke` or any live model call.
- Real-data cases under `prompts/*/cases/private/` stay gitignored and are only sent to providers listed in `repo_providers`.

## Where to look

- Workspace layout, `whetstone.toml`, `.env` variables, and harness/check formats: read `docs/workspace.md`.
- Layer and SDK import contracts: read `.importlinter`.
