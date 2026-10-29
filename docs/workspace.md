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
    editable.txt        the text Whetstone may rewrite, exactly as the source writes it
    brief.md            what the prompt is for, when it runs, its inputs and output shape (from /whetstone:new)
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
    runs/run-<id>/      one optimizing run: report.md, candidate.txt, cost.json, cards.json, split.json, run.json
    calibration/        the realistic cases the user approved, and their answers about real input sizes (from /whetstone:cases)
    labels.jsonl        swipes on the invented cases
```

## whetstone.toml

```toml
repo_providers = ["anthropic"]   # every model provider the repo already calls; real-data cases go only to these

[models]
judge = { provider = "openai", model = "gpt-5.5" }   # another family from the generator; needed once a prompt has a judge
# or judge = { provider = "cloudflare", model = "@cf/cloudflare/clef" }   (Clef on Workers AI; also "@cf/cloudflare/clef-flash")
rewrite = { via = "claude-code" }                    # the default; optional model = "<model>"; or { via = "api", model = "<model>" }

[prices]              # dollars per million input and output tokens, per model a run uses
"claude-haiku-5-5" = [0.10, 0.50]
"@cf/cloudflare/clef" = [0.24, 0]   # Clef charges input tokens only

[phone]
access = "lan"        # or "tailscale"; never a public tunnel

[apply]
target = "branch"     # or "folder"
skill = "build-kin"   # optional: the repo's own build skill; code edits and new builders are handed to it
```

Only the skills read `[apply]`; the engine takes `--folder` instead.

## .env

One key per purpose, so a leaked key can only do one thing:

| Variable | Used for |
|---|---|
| `GENERATION_API_KEY` | card generation, on the production provider |
| `JUDGE_API_KEY` | AI judges, when the judge provider is `openai` |
| `JUDGE_CF_ACCOUNT_ID` | AI judges on Cloudflare: the account id (32 hex characters), which goes in the URL path |
| `JUDGE_CF_API_TOKEN` | AI judges on Cloudflare: an API token scoped to Workers AI only, sent only as `Authorization: Bearer` |
| `REWRITE_API_KEY` | rewrites, only when `rewrite.via = "api"` |

The engine reads these from this file only, never from the shell. A key exported in the shell is ignored.

## prompt.toml

```toml
harness = "pnpm tsx whetstone/prompts/morning-follow-up/harness.ts"  # run from the workspace folder
provider = "anthropic"  # the only provider the engine calls today
model = "<production model>"
source = "../apps/backend/src/domain/ai/prompts/followUpPrompt.ts"  # the file the editable text lives in, from the workspace folder
apply = "exact"       # exact | code-edit; `whetstone apply-method` says which
reasons = ["too long", "sounds like a robot"]  # the swipe app's reason chips; optional

[placeholders]        # each placeholder in editable.txt, and the text it is built as
"${VOICE_EASY_READ}" = "Use short sentences. One idea per sentence."
```

- `harness`, `provider` and `model` are required. `source`, `apply`, `[placeholders]` and `editable.txt` are added once the harness is verified; `whetstone check` needs `editable.txt`, `verify-harness` does not.
- The production parameters (`max_tokens`, `temperature`, tools) are not repeated here: they are in the request the harness builds, which is the production request.

- `model` must equal the `model` in the harness's request. A mismatch means the harness has drifted from production.
- `apply` records how a winning version reaches the source:
  - `exact`: the editable text is one fixed string in `source`, so the engine replaces it;
  - `code-edit`: it is assembled from parts, or written differently in the source (escapes), so Claude edits the code on a branch.

  `whetstone apply-method <prompt>` looks for `editable.txt`'s text in `source` and prints `exact` (found exactly once) or `code-edit` and why. It writes nothing.

## editable.txt and placeholders

`editable.txt` is the part Whetstone may rewrite, byte for byte, nothing escaped: a trailing newline is part of it. It is stored the way the source writes it, with each interpolated constant kept as its placeholder (`${VOICE_EASY_READ}`, `{{name}}`), so shared rules stay in the code that owns them.

- The engine expands each placeholder from `[placeholders]` before every model call and before the "appears exactly once in the request" check: the expanded text must appear exactly once in the request the harness builds, counting the system prompt and every message's text.
- GEPA sees the placeholders and rewrites the text around them. A version that drops, changes or adds one scores 0. Moving one is allowed.
- A per-case value can't be in `editable.txt`: the text must be the same in every case's request.

## The harness contract

- **In:** one case file's JSON on stdin, without its `_about` (see Case summaries).
- **Out:** the exact request production sends, as JSON on stdout. That means the provider SDK's request body as-is: for Anthropic, `model`, `system`, `messages`, `max_tokens`, `temperature`, `tools`, `tool_choice` and so on.
- **Never:** call a model. Whetstone makes every model call itself, so it controls cost and which model runs.

It calls the repo's real prompt builder, so a change to the builder shows up in Whetstone without editing the harness.

## Case summaries

A case that is an object may carry `_about`: a few plain sentences on what happened in the input, so a grader can judge the card without reading the whole input.

```json
{"_about": "Athlete went to bed early last night and wrote they can't wait to wake up. Kin's latest read said their sleep has improved for a week. Their last two journal lines mention a race on Saturday.",
 "journal": "…", "reads": […]}
```

- Facts only: what the athlete wrote, what Kin said, what a later entry closed, the recent lines. Never a hint at the verdict: no "Good line: …", no "a good output would …", no expected answer, no "Tests: does it …?". A hint anchors the grader, and the anchored swipes become the labels the judges are measured against, so the hint leaks into the judges' score too.

- It is text; anything else stops `check` before any model call.
- No harness, model or judge ever gets it: the engine removes it before the case reaches the harness, and a card's `input` is the case without it. A case without `_about` reaches the harness byte for byte.
- The card and every swipe on it carry it as `about`. The app shows it above the output; the full input stays behind "Show input".

## Code checks

`checks/<name>.py` defines `check(output) -> list[str]`, returning one message per broken rule. An empty list means the check passed. A module-level `REASONS = ["too long"]` (a literal list of text, read without running the check) names the swipe reasons it stands for, for `whetstone reasons`. `output` is the tool input dict for a forced tool call, or the reply text otherwise.

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
- The judge must answer with `pass` or one of the `[fail]` names. A failing answer fails the case, with its text as the message.
- It sees the case input and the output. It runs on `[models] judge` in `whetstone.toml`. That's one call per case per judge.
  - `provider = "openai"`, with `JUDGE_API_KEY`: one Responses API call whose strict JSON schema allows only those answers.
  - `provider = "cloudflare"`, with `JUDGE_CF_ACCOUNT_ID` and `JUDGE_CF_API_TOKEN`: one Clef `choice` question whose options are those answers, each `[fail]` name described by its text. Clef scores only those options, so it can't answer anything else. The output comes first in Clef's `state`, the input after it: Clef truncates a `state` too long for its 64K-token window without saying so, and this way it loses input, never the output it judges.
- A judge and a code check can't share a name.
- Real-data cases go to a judge only when `repo_providers` lists the judge's provider (`openai` or `cloudflare`); otherwise `check` exits 2 before any call.

`whetstone check` reports judges among the code checks, marked `(judge)`. A card's `caught_by` names them without the mark, and its `judges` lists which of them are judges. A bad swipe with no reasons inherits only the code checks' names: on a card only judges caught, the app asks why, because a judge's own catch must never count as a grader agreeing with it.

## Reasons and agreement

- `whetstone reasons <prompt>` lists every left-swipe reason, and every note given without one, that no check stands for: a code check's name, or a judge's name, failing answer or `reasons`. With none, it prints `every reason has a check`.
- `whetstone agreement <prompt>` judges each swiped card once, from the input and output its label kept. Then it shows, per judge and grader:
  - **good:** of the cards the grader's latest swipe called good, how many the judge passed;
  - **bad:** of the cards called bad for this judge's rule (a reason that is its name, a failing answer or one of its `reasons`), how many it failed.

  Other bad swipes and skips don't count. Each judge is then:
  - **trusted:** at least 90% on both sides;
  - **warn:** 80% to 90%;
  - **untrusted:** below 80% on either side, or with no grader at 5 swipes on a side.

  Every grader with 5 or more swipes on a side must clear that side. It exits 1 when any judge is untrusted. `whetstone run` refuses to start against one, and shows the warnings of warned ones.

## Baseline

`whetstone baseline <prompt> --models <a>,<b>` runs every case on the production model and each listed model, all on the production provider, through every check and judge.
- It vets the suite as `check` does, and prints the call count first.
- It replaces the prompt's deck with all the outputs, shuffled. Card ids are `<deck-id>:<case-id>:<tag>`, and nothing on a card names its model.
- `runs/baseline-<deck-id>/cards.json` maps each card's tag to its model. It holds no outputs and no case ids, so it can be committed even when some cases are real data. It is written before the deck is replaced; if it can't be written, the run exits 2 and the old deck stays.
- Models listed twice run once, and the run goes case by case across the models, so a model that rejects the request fails on the first case.
- `report.md` says whether a model change alone fixes most of the production model's failures, then gives each model's pass counts and tokens.
- A model call that fails exits 2 and leaves the previous deck.

`whetstone baseline <prompt> --report` rewrites the latest run's report with each model's good, bad and skip swipes, from each grader's latest swipe on that run's cards.

## Optimizing

`whetstone run <prompt> --model <cheap model>` optimizes the editable part with GEPA (pinned at 0.1.4).
- It vets the run first: the suite as `check` does, the split, `[prices]`, the rewrite settings and key, and the judges. It refuses an untrusted judge (exit 2, with each judge's advice) and prints warned judges' warnings, after one judge call per swiped card per judge. Then it starts a worker in its own session, hands it the run's lock, and prints the run id and the log path, `.whetstone/runs/<prompt>-<id>.log`. The worker vets again (the judge calls too) and outlives the command and the Claude session. `--foreground` runs it in place. One run per prompt at a time; a second exits 2.
- Cases split about 40% training, 25% selection, 35% held back, each by a hash of its own id, so adding or removing other cases never moves it and a held-back case stays held back. In a small suite an empty set takes the nearest case from the biggest one. GEPA sees only training and selection cases. It needs at least 3 cases.
- Each output is the harness's request with only `model` and the editable text changed. Its score is the share of checks (code and judges) it passes, times a length factor: 1 up to 1.5 times the original's length, then 1.5 × original ÷ length. A version that drops, changes or adds a `{{name}}` or `${name}` placeholder, or is empty, scores 0 without a model call.
- Rewrites go through `[models] rewrite`: Claude Code's headless mode (`claude -p`, no tools, settings, plugins or MCP servers, in an empty folder, 10 minutes at most) or, with `via = "api"`, the Anthropic API with `REWRITE_API_KEY`. A failed Claude Code call says Claude Code's reason.
- `--budget` (default 150) caps GEPA's generation calls. The log prints a line for each version scored on all selection cases.
- The winner is the version with the best average on the selection cases, the original on a tie. With no new version, or none better than the original, the run exits 1 and says why; it writes no `candidate.txt` and no deck.
- The run folder, `prompts/<prompt>/runs/run-<id>/`:
  - `run.json` (the model it generated on), `split.json` (case ids per set) and `cost.json` (calls, tokens and dollars per role: generation, judge, rewrite, and gate for the judge check before the run), however the run ends: a run stopped by a broken check, a judge or a failed model call exits 2 and its report says why;
  - `report.md`: held-back results of the original and the candidate (cases passing every check, average score, each check), "within noise" when the averages differ by 0.03 or less, the rules now passing on every held-back case, the length change, the diff, the cost, and, when checks still fail, why it may be stuck;
  - `candidate.txt` and `cards.json` (card tag → original or candidate), with a winner;
  - a `.gitignore` of `*` when any case was real data.
- Dollars come from what a call reports (Claude Code does) or `[prices]`; a model with no price makes its role's dollars null and the report say "$ unknown".
- With a winner, the deck is replaced by the original's and the candidate's held-back outputs, shuffled, card ids `<run-id>:<case-id>:<tag>`. `whetstone run <prompt> --report` adds each version's good, bad and skip swipes to the latest run with a candidate.

`whetstone run <prompt> --production` prints the estimate for a run on the production model and the cap at twice that, and stops. The estimate scales the last cheap run (the latest run on another model): its tokens per generation at the production price, and its judge and rewrite dollars, for `--budget` plus twice the held-back cases. It exits 2 with no earlier cheap run, no price for a model paid by the token (production, the judge, an API rewrite model; Claude Code reports its own cost), or a cheap run whose dollars are unknown. `--production --yes` starts the run. GEPA stops before an output or a rewrite once the spend so far, plus one more output and one more rewrite at their averages and scoring the held-back cases, reaches the cap; the best version so far is the candidate, and the report says it stopped at the cap. The first rewrite has no average yet, so it can't be reserved for.

`make smoke` runs a live run on Haiku 5.5 (about $0.10), with `SMOKE_GENERATION_API_KEY` from the repo's `.env` and Claude Code for rewrites. `make check` skips it.

## Applying

`whetstone apply <prompt>` puts a run's candidate into `source`. It never promotes a prompt, never pushes and never touches `main`.

1. It takes the latest run with a candidate, or `--run <id>`, and names it first: `run-<id>, production model, 18/20 held-back passing vs 12/20 original`. It reads `run.json`, which a run with a winner writes with `model`, `original` (the editable text it optimized), `held_back` (`cases`, and how many passed every check on the `original` and the `candidate`) and `within_noise`. A run made before these fields existed must be run again.
2. It warns when nobody has swiped the run's blind deck, when the held-back result is within noise, or when the original's cards got more good swipes than the candidate's (each grader's latest swipe). With a warning and no `--yes`, it exits 1 and changes nothing.
3. It makes branch `whetstone/<prompt>-<run-id>` from the commit you are on, in a worktree of its own beside the repo, `<repo>.worktrees/whetstone-<prompt>-<run-id>`. Your checkout, branch and uncommitted work are never touched; uncommitted work is not on the new branch. It refuses a branch name that exists, and `editable.txt` must be committed, as the branch starts from your last commit.
4. **`exact`:** it replaces the run's original text in `source` (it must appear there exactly once), writes the candidate to `editable.txt`, and builds every case's request with the harness from the branch. When each one holds the candidate exactly once, it makes one local commit of only the source and `editable.txt`, naming the run's report, and removes the worktree; the branch stays. When one doesn't, the harness builds the request from somewhere else: apply removes the branch and worktree, exits 2, and says to set `apply = "code-edit"`. A harness that fails there (a fresh worktree has no `node_modules`) leaves the worktree uncommitted: set it up, then run `whetstone apply <prompt> --verify`.
5. **`code-edit`:** it makes the branch and worktree, changes nothing, and prints the worktree's path, the old text and the new text. Edit the code there, and run the repo's tests for the changed files. `whetstone apply <prompt> --verify` then builds every case's request from the branch: it exits 1 while one doesn't hold the candidate exactly once, and otherwise commits every change in the worktree with the new `editable.txt`, and lists the files it committed. Apply prints the exact `--verify` command, with `--run` and any `--folder`.

`--folder [<dir>]` runs the same flow, then writes `<dir>/<prompt>-<run-id>/change.patch` (it applies with `git apply`) and each changed file at its repo path, and deletes the branch. The folder defaults to `<workspace>/.whetstone/applied/`; one that exists is refused. Pass `--folder` to `--verify` too.

A workspace outside the repo can't build from the branch: `exact` commits only the source change, and says to rerun init's editable step after merging; `code-edit` is refused.

Commits refuse `main` and the remote's default branch.

## Real-data cases

A real-data source is one person's or group's data, used with their consent. `whetstone add-source <prompt> <source> --consented-by <who> --consented-on <YYYY-MM-DD>` makes its folder and writes `consent.toml`:

```toml
consented_by = "Levon"
consented_on = 2026-10-26
```

- A real-data case must sit directly in a source folder whose `consent.toml` names who consented and when. One loose in `cases/private/`, nested deeper, or under a missing or incomplete consent record stops `whetstone check` before any harness or model call.
- Real-data cases are sent only to providers in `repo_providers`. With no `repo_providers`, or a production provider not on it, `check` exits 2 before any call.
- Their labels stay in the source folder.

## One case

`whetstone check <prompt> --case <id>` runs one case and prints its output and its check results. The id is the case's path under `cases/` without `.json`, so a proposed case is `proposed/<id>`. It leaves the deck alone.

## Grading

Every case file must be JSON; one that isn't stops `check` before any model call. `whetstone check` saves its outputs as the prompt's deck, `.whetstone/decks/<prompt>.json`, replacing the last one: each card's id (`<deck-id>:<case-id>`), case id, `about` when the case has a summary, input, output, and the checks that caught it.

`whetstone serve <prompt>` starts the swipe server in the background and prints its link and QR code. The server:
- listens on the LAN address, the Tailscale address when `phone.access = "tailscale"`, or `--host`; never on every interface, never through a public tunnel;
- makes a new random token each start; the link carries it after `#`, so it is never sent in a URL or logged, and the app sends it as `Authorization: Bearer`;
- keeps its pid, port, prompt and token in `.whetstone/serve.json` (owner-only) and logs to `.whetstone/server.log`;
- stops 12 hours after it starts, whatever graders are doing, or with `whetstone serve --stop`; either way it removes `serve.json`. Swipes are saved as they're made, so the cut-off loses at most a note still being typed.
- refuses `0.0.0.0` and `::`, and exits 2 on an address it can't listen on or a Tailscale that isn't connected.
- runs one `serve` at a time per workspace. A second `serve` for the same prompt shows the same link; for another prompt it exits 2. `serve --stop` only signals a process that is this workspace's server, never one that has since reused its pid.

Each line of `labels.jsonl` is one swipe, self-contained so it outlives the deck:

```json
{"card_id": "…:first-day", "deck_id": "…", "case_id": "first-day", "about": "…", "input": {…}, "output": …, "caught_by": [],
 "grader": "Levon", "verdict": "bad", "reasons": ["too long"], "note": "…", "at": "2026-10-26T08:00:00+00:00"}
```

`about` is there only when the case has a summary. `verdict` is `good`, `bad` or `skip`. A bad swipe with no reasons on a card a code check caught takes those checks' names as reasons. `whetstone settle` adds a line with `"settled": true`, carrying the reasons of the latest swipe it sides with.

`whetstone disagreements <prompt>` lists cards where one grader's latest swipe is good and another's is bad, until `whetstone settle <prompt> <card> good|bad --grader <name> [--note <rule>]` records the call.

## whetstone check exit codes

| Code | Meaning |
|---|---|
| 0 | every case passes every check |
| 1 | some check failed |
| 2 | the setup is broken: workspace, whetstone.toml (including `[models] judge` once there's a judge), prompt.toml, no `editable.txt`, an unknown `--case`, no cases, a real-data case without consent or for a provider the repo doesn't use (the judge's included), harness (failing, invalid or over 120s), key, a failed model or judge call, a judge answer that isn't one of its choices, a judge rubric that won't load, or a check that won't load, crashes or returns something other than a list of messages |
