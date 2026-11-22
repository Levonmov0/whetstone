.PHONY: check typecheck contracts test apptest smoke

check: typecheck contracts test apptest

typecheck:
	uv run pyright

contracts:
	uv run lint-imports

test:
	uv run pytest -q

# The swipe app's own tests: app.html in jsdom, its server faked. jsdom is pinned in package-lock.json.
apptest: node_modules/.package-lock.json
	node --test tests/app/*.test.mjs

node_modules/.package-lock.json: package-lock.json
	npm ci --silent

# Real cheap models, about $0.10; needs SMOKE_GENERATION_API_KEY in .env and Claude Code logged in.
smoke:
	uv run pytest -q -m live
