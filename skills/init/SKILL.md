---
name: init
description: Point Whetstone at a prompt in this repo — workspace, theme, keys, harness, editable part.
disable-model-invocation: true
---

Set up Whetstone in the current repo, ending with a harness proven against a real production request. The workspace layout, the file formats and the harness contract are in `${CLAUDE_PLUGIN_ROOT}/docs/workspace.md`. Read it first; every file you write follows it.

Read the repo before asking anything. Every question should start from what the repo already says. Ask one numbered round per step, each question with what you found and your recommended answer.

The engine is `whetstone` on the Bash tool's PATH, built by the session-start hook. If it is missing, the user needs `uv` installed and a new session.

## 1. Workspace

Ask where the workspace lives: `whetstone/` in this repo (recommended when the repo will keep its harness), or a folder outside it.
- In a repo, work on a branch named `whetstone/<something>`, never on the default branch. Create the branch first if needed.
- Write `.gitignore` with `.env` and `prompts/*/cases/private/` before anything else.
- Write `whetstone.toml` with the user's answers for phone access and apply target, defaulting to `lan` and `branch`.

Done when `whetstone.toml` and `.gitignore` exist, and `git check-ignore <ws>/.env` confirms the key file is ignored.

## 2. Theme

Find the repo's design tokens: CSS variables, Tailwind config, a theme or tokens file, a design system package. Map them onto the variables in `${CLAUDE_PLUGIN_ROOT}/theme/default.css`, and write `theme.css` with only the values you found. With no tokens, copy the default theme and say so.

Done when `theme.css` exists and every value in it names its source file in a comment, or the file says it is the default.

## 3. Production model

Find the provider, model and parameters this prompt's production call uses, from the call site and its config. Ask only for what the code can't settle.

Done when you can name the provider, the model and every parameter, each with the file and line it came from.

## 4. Keys

Tell the user which variables the workspace needs (`GENERATION_API_KEY` now, the others when their features run). Ask them to create a key for each purpose and paste it into `<ws>/.env` themselves. Never read, print or write a key's value. Check that a key is present with `grep -c '^GENERATION_API_KEY=.' <ws>/.env`.

Done when that count is 1.

## 5. Prompt

Find the candidate prompts: prompt builders, template files, model call sites. List each with what it is for and where it lives, and ask which one. Name the prompt folder in kebab-case.

Done when the user has picked one.

## 6. Harness

Write `prompts/<name>/harness.*` in the repo's own language, calling the real prompt builder with the case's data, and printing the request body exactly as production passes it to the SDK.
- Write two or three cases in `cases/` from the repo's own fixtures or contracts, invented data only.
- Write `prompt.toml` with `harness`, `provider`, `model` and `apply`.

Capture one real production request for the same input. Run the production code path with the SDK client stubbed to record what it was given, for example in a one-off test. Save it outside the workspace and run:

```bash
whetstone verify-harness <name> --case <id> --expected <captured.json>
```

Fix the harness, not the capture, until it prints `harness matches the production request`. Then delete the one-off capture code.

Done when `verify-harness` exits 0.

## 7. Editable part

Agree with the user on the part Whetstone may rewrite: the prompt's own job text, never shared rules that other prompts use. Copy it exactly from a built request into `editable`.
- Set `apply` from its shape: `exact` for one fixed string in one file, `placeholders` when it holds variables, `code-edit` when it is assembled from parts.
- Tell the user which one it is and what it means for applying a winner.

Done when `whetstone check <name>` prints a line per case. With no checks yet, every case passes. It exits 2 first if `editable` doesn't appear exactly once.

## 8. Hand back

Run `whetstone check <name>` once and show its output. Then tell the user, in a few lines:
- where the workspace is;
- which prompt it points at;
- the production model;
- the apply method;
- that the next step is writing checks and cases.
