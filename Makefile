.PHONY: check typecheck contracts test smoke

check: typecheck contracts test

typecheck:
	uv run pyright

contracts:
	uv run lint-imports

test:
	uv run pytest -q

# Real cheap models, about $0.10; needs SMOKE_GENERATION_API_KEY in .env and Claude Code logged in.
smoke:
	uv run pytest -q -m live
