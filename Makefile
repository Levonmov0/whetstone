.PHONY: check typecheck contracts test

check: typecheck contracts test

typecheck:
	uv run pyright

contracts:
	uv run lint-imports

test:
	uv run pytest -q
