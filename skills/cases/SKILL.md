---
name: cases
description: Propose 20 to 30 realistic and edge-case inputs for a Whetstone prompt, and add only the ones the user approves.
disable-model-invocation: true
---

Build a prompt's case suite with the user. The workspace layout and the case format are in `${CLAUDE_PLUGIN_ROOT}/docs/workspace.md`. Read it first.

The engine is `whetstone` on the Bash tool's PATH. Every case is invented unless the user brings a real-data source (step 4).

## 1. Read before proposing

Find the prompt's harness (`prompts/<name>/prompt.toml`), the data it builds from, and the repo's contracts for that data: types, schemas, fixtures, seed data, fake backends. Read the existing cases in `cases/`. Note what a case's JSON must hold for the harness to build a request.

Done when you can name every field a case carries, each with the file that defines it.

## 2. Propose

Write 20 to 30 cases into `cases/proposed/<id>.json`, ids in kebab-case that say what the case is (`first-day-no-wearable`). The engine never runs anything in `proposed/`.
- About two thirds realistic: the common days, spread across the real range of each field.
- About one third edge cases: missing or empty data, first and last days, extreme values, conflicting signals, long text, whatever the contracts allow that the prompt might handle badly.
- Invented data only. Never copy a real person's data from the repo, logs or a database.
- Skip any case already in `cases/`.

Run each through the harness once to prove it builds (`whetstone check` would also call the model, so instead pipe one file into the harness command from `prompt.toml`, from the workspace folder). Fix any case it rejects.

## 3. Review with the user

Show the proposals as a numbered list, one line each: the id and what it tests. Then ask the user to keep, edit or delete each one, and whether to add their own. Accept answers like "keep all but 4 and 9" or "make 12 a rest day".
- **Keep:** move the file from `cases/proposed/` to `cases/`.
- **Edit:** change it as asked, show the result, then move it.
- **Delete:** delete the file.
- **Add:** write the user's case to `cases/<id>.json` after showing it.

Nothing enters `cases/` without the user's yes. When the review ends, delete what is left in `proposed/`.

Done when `proposed/` is empty and you have told the user how many cases the suite now has.

## 4. Real-data cases (only when the user asks)

Real data comes from an opt-in source: the user's own diary, a teammate's, consenting users. For each source, ask who consented and on what date, then run:

```bash
whetstone add-source <prompt> <source> --consented-by "<who>" --consented-on <YYYY-MM-DD>
```

It makes `cases/private/<source>/`, records the consent, and keeps the folder out of git. Put that source's cases in that folder only.

Real-data cases are only sent to the providers in `whetstone.toml`'s `repo_providers`. If it's missing, tell the user and ask which providers the repo already uses; never add one the repo doesn't call today.

Done when `git check-ignore <ws>/prompts/<prompt>/cases/private/<source>/consent.toml` confirms the folder is ignored.
