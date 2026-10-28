---
name: fix
description: Take a prompt that misbehaves, from a pasted bad output or its name, through cases, checks, grading and a run to an applied candidate. Rerun it to continue where it stopped.
disable-model-invocation: true
---

Guide the user from "this prompt is bad" to a better version on a branch. Each step below is also a skill of its own; this one decides which comes next and runs it. The workspace formats are in `${CLAUDE_PLUGIN_ROOT}/docs/workspace.md`.

The engine is `whetstone` on the Bash tool's PATH.

## 1. The prompt

Find which prompt the user means: the one they named, or the one whose output they pasted (search the repo's prompt builders for its wording or shape). If `prompts/<name>/` doesn't exist in the workspace, run `/whetstone:init` for it first. The existing prompt is the starting point: its text is what the run will improve.

Done when `whetstone check <name>` runs.

## 2. A pasted bad output

Skip this step without a pasted output. Otherwise it becomes a case and a check.

- **The case.** Ask what situation produced the output. By default, write an invented lookalike for that situation from the repo's data contracts, in the calibrated shape (`prompts/<name>/calibration/`; calibrate first through step 2 of `/whetstone:cases` if it is empty). Use the real input only when the user chooses it, as a real-data case through `whetstone add-source` with the consent recorded.
- **The check.** Ask why the output is bad, as with a left swipe. When no existing check covers that reason, propose one through `/whetstone:checks` (code when code can decide it, a judge otherwise), and add it on the user's yes.

Then run the new case:

```bash
whetstone check <name> --case <id>
```

When it doesn't fail, say so plainly: outputs vary between runs, so this one case doesn't reproduce the problem. Keep the case and the check, and propose one or two more cases in the same situation.

Done when the case and the check are in the suite, and the user has seen whether the case fails.

## 3. The next step

There is no state file. Work out where the user is from the workspace, and take the first step that applies, each through its own skill:

| The workspace shows | Next |
|---|---|
| no approved cases, or no calibration | `/whetstone:cases` |
| no checks | `/whetstone:checks` |
| cards in the deck nobody swiped | `/whetstone:grade` |
| `whetstone reasons <name>` lists a reason | `/whetstone:checks`, to turn it into a check |
| `whetstone agreement <name>` exits 1 | more swipes through `/whetstone:grade`, or a sharper judge through `/whetstone:checks` |
| no baseline run in `runs/` | `whetstone baseline <name> --models …` (if a model change alone fixes it, say so and stop) |
| no run, or only failed ones | the cheap run in `/whetstone:run` |
| a run with a candidate whose cards nobody swiped | the blind swipe in `/whetstone:run` |
| a cheap run's candidate swiped, and the user wants it on production | the production run in `/whetstone:run` |
| a swiped candidate the user wants | `/whetstone:apply` |

Before each step, say in one line where the user is and what comes next ("12 cases, 3 checks, no swipes yet: grading next").

Done when `/whetstone:apply` has committed a candidate, or the user stops. When they stop, tell them that rerunning `/whetstone:fix <name>` continues from here.
