---
name: cases
description: Propose 20 to 30 realistic and edge-case inputs for a Whetstone prompt, and add only the ones the user approves.
disable-model-invocation: true
---

Build a prompt's case suite with the user. The workspace layout and the case format are in `${CLAUDE_PLUGIN_ROOT}/docs/workspace.md`. Read it first.

The engine is `whetstone` on the Bash tool's PATH. Every case is invented unless the user brings a real-data source (step 5).

## 1. Read before proposing

Find the prompt's harness (`prompts/<name>/prompt.toml`), the data it builds from, and the repo's contracts for that data: types, schemas, fixtures, seed data, fake backends. Read the existing cases in `cases/`. Note what a case's JSON must hold for the harness to build a request.

Also read `prompts/<name>/brief.md` when it exists, and how the repo collects each input (sync jobs, seed data, upstream prompts).

Done when you can name every field a case carries, each with the file that defines it.

## 2. Calibrate

Invented cases come out unrealistically small: a few lines and one night of sleep, where a real input carries 500 to 1,000+ characters and weeks of wearable data. Calibrate the size before proposing anything. When `prompts/<name>/calibration/` already holds approved examples and answers, read them and go to step 3.

1. Ask only what the repo couldn't settle: how many days of data a typical input holds, how long journal entries run, how long an upstream insight feeding this prompt is.
2. Write 2 to 3 full-size typical cases in `cases/proposed/`. Write any input that is another prompt's output the way that prompt writes it.
3. Show each one **in full**, with the output the current prompt gives for it (`whetstone check <name> --case proposed/<id>`).
4. Ask whether they are realistic. On "no, because…", fix them and show them again.

Done when the user calls every one realistic. Save the approved examples and the user's answers in `prompts/<name>/calibration/` (`examples/<id>.json` and `answers.md`), so later rounds and `/whetstone:fix` reuse them without asking again.

## 3. Propose

Write 20 to 30 cases into `cases/proposed/<id>.json`, in the calibrated shape and size, ids in kebab-case that say what the case is (`first-day-no-wearable`). `whetstone check` runs a proposed case only when it is named with `--case`; a plain `check`, a baseline or a run never does.
- About two thirds realistic: the common days, spread across the real range of each field.
- About one third edge cases: missing or empty data, first and last days, extreme values, conflicting signals, long text, whatever the contracts allow that the prompt might handle badly. Name each one as an edge case in its id and in the review list, never as a typical day.
- Invented data only. Never copy a real person's data from the repo, logs or a database.
- Skip any case already in `cases/`.
- Give each case an `_about` as its first key: two or three plain sentences on what happened in the input, so the card can be judged without reading the full input. Facts only: what the athlete wrote, what Kin said, what a later entry closed, the recent lines. Never hint at the verdict: no "Good line: …", no "a good output would …", no expected answer, no "Tests: does it …?". The grader reads `_about` before the output, so a hint anchors their swipe, and the swipes are the labels the judges are measured against. For example: "Athlete went to bed early last night and wrote they can't wait to wake up. Kin's latest read said their sleep has improved for a week." See Case summaries in `workspace.md`.

Run each through the harness once to prove it builds (`whetstone check` would also call the model, so instead pipe one file, without its `_about`, into the harness command from `prompt.toml`, from the workspace folder: `jq 'del(._about)' cases/proposed/<id>.json | <harness>`). Fix any case it rejects.

## 4. Review with the user

Show the proposals as a numbered list, one line each: the id and what it tests. What it tests goes in this list only, never in `_about`. Then ask the user to keep, edit or delete each one, and whether to add their own. Accept answers like "keep all but 4 and 9" or "make 12 a rest day".
- **Keep:** move the file from `cases/proposed/` to `cases/`.
- **Edit:** change it as asked, and its `_about` to match, show the result, then move it.
- **Delete:** delete the file.
- **Add:** write the user's case to `cases/<id>.json` after showing it.

Nothing enters `cases/` without the user's yes. When the review ends, delete what is left in `proposed/`.

Done when `proposed/` is empty and you have told the user how many cases the suite now has.

## 5. Real-data cases (only when the user asks)

Real data comes from an opt-in source: the user's own diary, a teammate's, consenting users. For each source, ask who consented and on what date, then run:

```bash
whetstone add-source <prompt> <source> --consented-by "<who>" --consented-on <YYYY-MM-DD>
```

It makes `cases/private/<source>/`, records the consent, and keeps the folder out of git. Put that source's cases in that folder only.

Real-data cases are only sent to the providers in `whetstone.toml`'s `repo_providers`. If it's missing, tell the user and ask which providers the repo already uses; never add one the repo doesn't call today.

Done when `git check-ignore <ws>/prompts/<prompt>/cases/private/<source>/consent.toml` confirms the folder is ignored.
