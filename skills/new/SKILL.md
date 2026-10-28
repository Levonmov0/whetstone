---
name: new
description: Write a new prompt for this repo from an interview: brief, checks, first prompt, builder and harness, on a branch of its own, then through cases, grading and a run to apply. Rerun it to continue where it stopped.
disable-model-invocation: true
---

Guide the user from "I need a prompt that does X" to a tested prompt on a branch. The workspace formats are in `${CLAUDE_PLUGIN_ROOT}/docs/workspace.md`. Read it first.

The engine is `whetstone` on the Bash tool's PATH. The workspace must exist; if `whetstone.toml` is missing, run steps 1 to 4 of `/whetstone:init` first.

When `prompts/<name>/` already exists on a `whetstone/<name>-new` branch, the user is resuming: go to step 6.

## 1. Branch first

Name the prompt in kebab-case with the user. Make a worktree branch from the commit the user is on, and do everything that follows inside it:

```bash
git worktree add -b whetstone/<name>-new ../<repo>.worktrees/whetstone-<name>-new HEAD
```

The user's checkout stays as it is. The whole flow, apply included, runs on this branch, and apply branches off it.

Done when the worktree exists and you are working in it.

## 2. Interview

Read the repo before asking anything: where its prompts live, the data the new prompt could use and that data's contracts, its voice rules and docs, how its features call a model. Then ask only what the repo can't say, one numbered round, each question with what you found:
- what the prompt is for, and when it runs;
- its inputs;
- the shape of its output;
- what must never happen.

Sort every answer into one of two kinds:
- **Context** (purpose, when it runs, inputs, output shape) goes into `prompts/<name>/brief.md`.
- **A rule** ("never more than two sentences", "never assume they did the workout") becomes a proposed check in `checks/proposed/`, through `/whetstone:checks`: code when code can decide it, a judge otherwise. Show each one in chat as a short card (its name, the rule, code or judge), and ask the user to approve it.

Before moving on, show the full list of approved checks and the brief again.

Done when `brief.md` is written and the user has approved or dropped every proposed check.

## 3. First prompt

Draft the prompt from `brief.md`, the repo's docs and voice rules, and its data contracts, following prompt-writing best practice: the job first, the inputs named, the output shape stated, the approved rules written in. Show it to the user and revise it until they accept it.

Done when the user accepts the draft.

## 4. Builder and harness

The builder is product code: the function the feature will call to build the request. The harness calls it, so the feature and Whetstone share one builder.
- **With `[apply] skill` set in `whetstone.toml`**, hand the builder to that skill with a brief: the brief, the accepted prompt, the inputs and where they come from, the output shape, and that it is done when the builder has tests and returns the request body for the repo's model SDK.
- **Otherwise**, write it yourself in the repo's language, next to its other prompt builders, with a test beside it.

**A repurposed prompt** (the same inputs as an existing prompt, a new purpose) gets a new builder that calls the existing data assembly (for Kin, a function like `buildTodayInsightContext`). Leave the old prompt and its builder untouched.

Then write `prompts/<name>/harness.*`, `prompt.toml` and `editable.txt` as in steps 6 and 7 of `/whetstone:init`. Skip `verify-harness`: there is no production request to capture yet, and the feature and the harness share the builder.

Wire the builder into a feature only when the user asks, on this same branch.

Done when `whetstone apply-method <name>` prints a method and that method is recorded in `prompt.toml`.

## 5. Cases

Run `/whetstone:cases`. It calibrates real input sizes with the user first.

Done when the suite has approved cases.

## 6. The rest of the flow

Work out the next step from the workspace and take the first that applies, as in the table in step 3 of `/whetstone:fix`: checks, grading, new reasons as checks, judge agreement, a baseline, the cheap run and its report, the blind swipe, the production run if the user wants it, then `/whetstone:apply`. Before each one, say in one line where the user is and what comes next.

Done when `/whetstone:apply` has committed a candidate on a branch off `whetstone/<name>-new`, or the user stops. When they stop, tell them that rerunning `/whetstone:new` in the worktree continues from here.
