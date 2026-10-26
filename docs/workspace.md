# The Whetstone workspace

The workspace is the one place Whetstone keeps a repo's settings, keys, theme and prompts. The engine finds it from `--workspace`, else `./whetstone.toml`, else `./whetstone/whetstone.toml`. It never looks in parent folders.

```
<workspace>/
  whetstone.toml        repo-level settings
  .env                  keys, one per purpose; always gitignored
  .gitignore            lists .env and prompts/*/cases/private/
  theme.css             the swipe app's theme
  .whetstone/           the engine's own files: decks, server state and log; ignores itself in git
  prompts/<name>/
    prompt.toml         the prompt's settings
    harness.*           builds the production request (any language)
    cases/<id>.json     one case per file; any JSON
    cases/proposed/     cases Claude proposed and the user hasn't approved; never run
    cases/private/<source>/
      consent.toml      who consented to this source, and when
      <id>.json         real-data cases, ids private/<source>/<id>
      labels.jsonl      swipes on this source's cases
      .gitignore        "*": the folder ignores itself in git
    checks/<name>.py    code checks
    labels.jsonl        swipes on the invented cases
```

## whetstone.toml

```toml
repo_providers = ["anthropic"]   # every model provider the repo already calls; real-data cases go only to these

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
provider = "anthropic"  # the only provider the engine calls today
model = "<production model>"
editable = '''<the exact text Whetstone may rewrite>'''
apply = "exact"       # exact | placeholders | code-edit
reasons = ["too long", "sounds like a robot"]  # the swipe app's reason chips; optional
```

- `harness`, `provider` and `model` are required. `editable` and `apply` are added once the harness is verified; `whetstone check` needs `editable`, `verify-harness` does not.
- The production parameters (`max_tokens`, `temperature`, tools) are not repeated here: they are in the request the harness builds, which is the production request.

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

## Real-data cases

A real-data source is one person's or group's data, used with their consent. `whetstone add-source <prompt> <source> --consented-by <who> --consented-on <YYYY-MM-DD>` makes its folder and writes `consent.toml`:

```toml
consented_by = "Levon"
consented_on = 2026-10-26
```

- A case under `cases/private/` outside a source folder with a `consent.toml` stops `whetstone check` before any harness or model call.
- Real-data cases are sent only to providers in `repo_providers`. With no `repo_providers`, or a production provider not on it, `check` exits 2 before any call.
- Their labels stay in the source folder.

## Grading

`whetstone check` saves its outputs as the prompt's deck, `.whetstone/decks/<prompt>.json`, replacing the last one: each card's id (`<deck-id>:<case-id>`), case id, input, output, and the checks that caught it.

`whetstone serve <prompt>` starts the swipe server in the background and prints its link and QR code. The server:
- listens on the LAN address, the Tailscale address when `phone.access = "tailscale"`, or `--host`; never on every interface, never through a public tunnel;
- makes a new random token each start; the link carries it after `#`, so it is never sent in a URL or logged, and the app sends it as `Authorization: Bearer`;
- keeps its pid, port, prompt and token in `.whetstone/serve.json` (owner-only) and logs to `.whetstone/server.log`;
- stops after 12 hours with no API use, or with `whetstone serve --stop`. A second `serve` for the same prompt shows the same link; for another prompt it exits 2.

Each line of `labels.jsonl` is one swipe, self-contained so it outlives the deck:

```json
{"card_id": "…:first-day", "deck_id": "…", "case_id": "first-day", "input": {…}, "output": …, "caught_by": [],
 "grader": "Levon", "verdict": "bad", "reasons": ["too long"], "note": "…", "at": "2026-10-26T08:00:00+00:00"}
```

`verdict` is `good`, `bad` or `skip`. A bad swipe with no reasons on a card a check caught takes the check names as reasons. `whetstone settle` adds a line with `"settled": true`.

`whetstone disagreements <prompt>` lists cards where one grader's latest swipe is good and another's is bad, until `whetstone settle <prompt> <card> good|bad --grader <name> [--note <rule>]` records the call.

## whetstone check exit codes

| Code | Meaning |
|---|---|
| 0 | every case passes every check |
| 1 | some check failed |
| 2 | the setup is broken: workspace, whetstone.toml, prompt.toml, no cases, a real-data case without consent or for a provider the repo doesn't use, harness (failing, invalid or over 120s), key, a failed model call, or a check that won't load, crashes or returns something other than a list of messages |
