# The Whetstone workspace

The workspace is the one place Whetstone keeps a repo's settings, keys, theme and prompts. The engine finds it from `--workspace`, else `./whetstone.toml`, else `./whetstone/whetstone.toml`. It never looks in parent folders.

```
<workspace>/
  whetstone.toml        repo-level settings
  .env                  keys, one per purpose; always gitignored
  .gitignore            lists .env and prompts/*/cases/private/
  theme.css             the swipe app's theme: only the repo's tokens, served on top of Whetstone's own
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
    checks/<name>.judge.toml   judge rubrics, one rule each
    checks/proposed/    checks Claude proposed and the user hasn't approved; never run
    runs/baseline-<id>/ one baseline run: cards.json (card id → model) and report.md
    labels.jsonl        swipes on the invented cases
```

## whetstone.toml

```toml
repo_providers = ["anthropic"]   # every model provider the repo already calls; real-data cases go only to these

[models]
judge = { provider = "openai", model = "gpt-5.5" }   # another family from the generator; needed once a prompt has a judge
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

## Judges

A judge is one rule that code can't decide, asked of the judge model as one question. `checks/<name>.judge.toml`:

```toml
question = "Does the line assume whether the athlete did what Kin advised?"
guide = '''Optional: what counts and what doesn't, with examples.'''
pass = "no"
reasons = ["assumes the outcome"]   # optional: the swipe reasons this judge stands for
[fail]                              # each failing answer, and the reason it shows
yes = "assumes whether they did Kin's advice"
```

- Put `reasons` above `[fail]`: in TOML, every key after `[fail]` belongs to it.
- The judge must answer with `pass` or one of the `[fail]` names (the request's JSON schema allows only those). A failing answer fails the case, with its text as the message.
- It sees the case input and the output. It runs on `[models] judge` in `whetstone.toml`, which must be `provider = "openai"`, with `JUDGE_API_KEY`. That's one call per case per judge.
- A judge and a code check can't share a name.
- Real-data cases go to a judge only when `repo_providers` lists `openai`; otherwise `check` exits 2 before any call.

`whetstone check` reports judges among the code checks, marked `(judge)`. A card's `caught_by` names them without the mark.

## Reasons and agreement

- `whetstone reasons <prompt>` lists every left-swipe reason, and every note given without one, that no check stands for: a code check's name, or a judge's name, failing answer or `reasons`. With none, it prints `every reason has a check`.
- `whetstone agreement <prompt>` judges each swiped card once, from the input and output its label kept. Then it shows, per judge and grader:
  - **good:** of the cards the grader's latest swipe called good, how many the judge passed;
  - **bad:** of the cards called bad for this judge's rule (a reason that is its name, a failing answer or one of its `reasons`), how many it failed.

  Other bad swipes and skips don't count. Each judge is then:
  - **trusted:** at least 90% on both sides;
  - **warn:** 80% to 90%;
  - **untrusted:** below 80% on either side, or with no grader at 5 swipes on a side.

  Every grader with 5 or more swipes on a side must clear that side. It exits 1 when any judge is untrusted, and the optimizer refuses to run against one.

## Baseline

`whetstone baseline <prompt> --models <a>,<b>` runs every case on the production model and each listed model, all on the production provider, through every check and judge.
- It vets the suite as `check` does, and prints the call count first.
- It replaces the prompt's deck with all the outputs, shuffled. Card ids are `<deck-id>:<case-id>:<tag>`, and nothing on a card names its model.
- `runs/baseline-<deck-id>/cards.json` maps each card id to its model. It holds no outputs.
- `report.md` says whether a model change alone fixes most of the production model's failures, then gives each model's pass counts and tokens.
- A model call that fails exits 2 and leaves the previous deck.

`whetstone baseline <prompt> --report` rewrites the latest run's report with each model's good, bad and skip swipes, from each grader's latest swipe on that run's cards.

## Real-data cases

A real-data source is one person's or group's data, used with their consent. `whetstone add-source <prompt> <source> --consented-by <who> --consented-on <YYYY-MM-DD>` makes its folder and writes `consent.toml`:

```toml
consented_by = "Levon"
consented_on = 2026-10-26
```

- A real-data case must sit directly in a source folder whose `consent.toml` names who consented and when. One loose in `cases/private/`, nested deeper, or under a missing or incomplete consent record stops `whetstone check` before any harness or model call.
- Real-data cases are sent only to providers in `repo_providers`. With no `repo_providers`, or a production provider not on it, `check` exits 2 before any call.
- Their labels stay in the source folder.

## Grading

Every case file must be JSON; one that isn't stops `check` before any model call. `whetstone check` saves its outputs as the prompt's deck, `.whetstone/decks/<prompt>.json`, replacing the last one: each card's id (`<deck-id>:<case-id>`), case id, input, output, and the checks that caught it.

`whetstone serve <prompt>` starts the swipe server in the background and prints its link and QR code. The server:
- listens on the LAN address, the Tailscale address when `phone.access = "tailscale"`, or `--host`; never on every interface, never through a public tunnel;
- makes a new random token each start; the link carries it after `#`, so it is never sent in a URL or logged, and the app sends it as `Authorization: Bearer`;
- keeps its pid, port, prompt and token in `.whetstone/serve.json` (owner-only) and logs to `.whetstone/server.log`;
- stops 12 hours after it starts, whatever graders are doing, or with `whetstone serve --stop`; either way it removes `serve.json`. Swipes are saved as they're made, so the cut-off loses at most a note still being typed.
- refuses `0.0.0.0` and `::`, and exits 2 on an address it can't listen on or a Tailscale that isn't connected.
- runs one `serve` at a time per workspace. A second `serve` for the same prompt shows the same link; for another prompt it exits 2. `serve --stop` only signals a process that is this workspace's server, never one that has since reused its pid.

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
| 2 | the setup is broken: workspace, whetstone.toml (including `[models] judge` once there's a judge), prompt.toml, no cases, a real-data case without consent or for a provider the repo doesn't use (the judge's included), harness (failing, invalid or over 120s), key, a failed model or judge call, a judge answer that isn't one of its choices, a judge rubric that won't load, or a check that won't load, crashes or returns something other than a list of messages |
