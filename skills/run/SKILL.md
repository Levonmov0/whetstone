---
name: run
description: Optimize a prompt's editable part with GEPA, cheaply first, then read the report, blind-swipe the winner, and, if wanted, run on the production model.
disable-model-invocation: true
---

Let GEPA rewrite a prompt's editable part until its checks pass, and show whether the winner is better on cases it never saw. The workspace layout is in `${CLAUDE_PLUGIN_ROOT}/docs/workspace.md`.

The engine is `whetstone` on the Bash tool's PATH. Run it from the workspace folder, or pass `--workspace`.

## 1. Before a run

- The prompt needs at least 3 approved cases and its checks. Every judge must be trusted or warned by `whetstone agreement <prompt>`; the run refuses an untrusted one and says how to fix it (see `/whetstone:checks`).
- If the user's swipes are old or few, offer a fresh round of `/whetstone:grade` first, then `whetstone agreement` again. A judge calibrated on more swipes is a judge the optimizer can't game as easily.
- `whetstone.toml` needs a `[prices]` entry for every model the run uses, in dollars per million input and output tokens, or the cost record says "unknown" (and a production run refuses to start). Fill it from the provider's price page and show the user what you wrote.
- Rewrites run through Claude Code's headless mode by default, on the user's own login. For the API instead, set `rewrite = { via = "api", model = "…" }` under `[models]` and ask the user to paste `REWRITE_API_KEY` into `<ws>/.env` themselves. Never read, print or write its value; check it's there with `grep -cE '^(export )?REWRITE_API_KEY *= *[^ ]' <ws>/.env`.

## 2. The cheap run

Pick the cheapest model of the production provider that accepts the production request (for Anthropic, Haiku), and say so.

```bash
whetstone run <prompt> --model <cheap model>
```

`--budget` caps GEPA's generation calls (150 by default, about a dollar on Haiku). It vets the run first (the suite, the split, prices, the rewrite settings and the judges), then returns and prints the run's log path; the run goes on in the background even after this session ends. One run per prompt at a time.

Follow the log with `tail` and relay its progress lines in plain words ("version 3: 17 of 20 checks passing on selection cases"). The run ends with:
- **exit 0:** a candidate. Go on to the report.
- **exit 1:** no winner. "GEPA produced no new version" means every rewrite failed or changed nothing; the message says the last rewrite error. "No new version beat the original" means it tried and didn't improve. Read the report's "Why it may be stuck" with the user: a check that never passed on a case needs more input data or a different model, not a better prompt; two checks that never pass together may contradict each other, which is a finding worth fixing in the checks.
- **exit 2:** a broken setup, said in the log. Fix it and run again.

## 3. The report

`prompts/<prompt>/runs/run-<id>/report.md`. Walk the user through it:
- held-back cases, original against candidate: these are cases GEPA never saw, so they are the real result. A gap marked "within noise" is no result;
- the diff and the length change. Read the candidate with the user: GEPA protects only what is checked, so look for voice drift, rules written for one case, and test feedback copied into the prompt;
- which rules now pass, and the cost.

## 4. The blind swipe

The run replaced the prompt's deck with the original's and the candidate's outputs on the held-back cases, shuffled, with nothing saying which is which. Start `/whetstone:grade` for the user to swipe them, then:

```bash
whetstone run <prompt> --report
```

It adds each version's good, bad and skip counts to the report. "Better" means the user prefers it, not only that the score rose.

## 5. The production run (only if the user wants it)

```bash
whetstone run <prompt> --production
```

It prints an estimate, scaled from the last cheap run, and the cap at twice that, and spends nothing. Show both to the user and wait for an explicit yes. Then:

```bash
whetstone run <prompt> --production --yes
```

It runs on the production model and stops at the cap, keeping the best version so far. Go through sections 3 and 4 again with its report.

Nothing here changes the repo's source. Applying a candidate is `/whetstone:apply`.
