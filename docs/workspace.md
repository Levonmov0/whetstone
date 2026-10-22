# The Whetstone workspace

The workspace is the one place Whetstone keeps a repo's settings, keys, theme and prompts. The engine finds it from `--workspace`, else `./whetstone.toml`, else `./whetstone/whetstone.toml`. It never looks in parent folders.

```
<workspace>/
  whetstone.toml        repo-level settings
  .env                  keys, one per purpose; always gitignored
  .gitignore            lists .env and prompts/*/cases/private/
  theme.css             the swipe app's theme
  prompts/<name>/
    prompt.toml         the prompt's settings
    harness.*           builds the production request (any language)
    cases/<id>.json     one case per file; any JSON
    cases/private/      real-data cases; always gitignored
    checks/<name>.py    code checks
```

## whetstone.toml

```toml
[models]
judge = { provider = "openai", model = "<model>" }   # another family from the generator
rewrite = { via = "claude-code" }                    # or { via = "api", model = "<model>" }

[phone]
access = "lan"        # or "tailscale"; never a public tunnel

[apply]
target = "branch"     # or "folder"
```

## .env

One key per purpose, so a leaked key can only do one thing:

| Variable | Used for |
|---|---|
| `GENERATION_API_KEY` | card generation, on the production provider |
| `JUDGE_API_KEY` | AI judges, on the judge provider |
| `REWRITE_API_KEY` | rewrites, only when `rewrite.via = "api"` |

The engine reads these from this file only, never from the shell. A key exported in the shell is ignored.

## prompt.toml

```toml
harness = "pnpm tsx whetstone/prompts/morning-follow-up/harness.ts"  # run from the workspace folder
editable = "<the exact text Whetstone may rewrite>"
provider = "anthropic"
model = "<production model>"
apply = "exact"       # exact | placeholders | code-edit
```

- `editable` must appear exactly once in the request the harness builds, counting the system prompt and every message's text.
- `model` must equal the `model` in the harness's request. A mismatch means the harness has drifted from production.
- `apply` records how a winning version reaches the source:
  - `exact`: the editable text is one fixed string in one source file;
  - `placeholders`: it contains variables that must survive the swap;
  - `code-edit`: it is assembled from several parts, so Claude edits the code on a branch.

## The harness contract

- **In:** one case file's JSON on stdin.
- **Out:** the exact request production sends, as JSON on stdout. That means the provider SDK's request body as-is: for Anthropic, `model`, `system`, `messages`, `max_tokens`, `temperature`, `tools`, `tool_choice` and so on.
- **Never:** call a model. Whetstone makes every model call itself, so it controls cost and which model runs.

It calls the repo's real prompt builder, so a change to the builder shows up in Whetstone without editing the harness.

## Code checks

`checks/<name>.py` defines `check(output) -> list[str]`, returning one message per broken rule. An empty list means the check passed. `output` is the tool input dict for a forced tool call, or the reply text otherwise.

## whetstone check exit codes

| Code | Meaning |
|---|---|
| 0 | every case passes every check |
| 1 | some check failed |
| 2 | the setup is broken: workspace, harness, key or a crashing check |
