---
name: apply
description: Put a Whetstone run's candidate into the repo's source, on a new branch or into a folder, after the user agrees to any warning.
disable-model-invocation: true
---

Take a run's winning version of a prompt's editable part into the code. How apply works, its warnings and its targets are in `${CLAUDE_PLUGIN_ROOT}/docs/workspace.md` under "Applying". Read it first.

The engine is `whetstone` on the Bash tool's PATH. Run it from the workspace folder, or pass `--workspace`. Nothing here pushes, opens a PR or touches the user's checkout: the change lands on a new local branch, or in a folder.

## 1. The run and its warnings

Read `[apply] target` and `[apply] skill` in `whetstone.toml`. For the folder target, ask which folder, defaulting to `<workspace>/.whetstone/applied/`, and pass `--folder <dir>` to every apply command below.

```bash
whetstone apply <prompt>
```

Add `--run <id>` when the user named a run. Its first line names the run and its held-back result; relay it. When it exits 1, show each warning in plain words and ask whether to apply anyway:
- no blind swipe yet: offer `/whetstone:grade` on the run's deck first;
- within noise: the candidate may be no better than the original;
- the blind swipe preferred the original: the score rose, but the user liked it less.

Rerun with `--yes` only after the user says yes.

Done when apply has exited 0 or 2, or the user chose not to apply.

## 2. `exact`

Apply replaces the text, checks the branch and commits. Tell the user the branch name and that nothing was pushed.

When it stops because the harness failed on the branch, set up the worktree it names the way the repo sets up a checkout (for a pnpm repo, `pnpm install` there), then run the `--verify` command it prints.

When it says the harness doesn't build the request from the source, the text is assembled somewhere else: apply removed its branch. Tell the user, set `apply = "code-edit"` in `prompt.toml` with their yes, and start again from step 1.

Done when the output says the candidate was committed.

## 3. `code-edit`

Apply prints the worktree, the old text, the new text and the `--verify` command that finishes it (it names the run, and the folder when there is one). The edit is code work in that worktree:
- **With `[apply] skill` set**, hand the edit to that skill with this brief: the worktree path and branch, the old text and the new text, that the prompt the code builds must hold the new text exactly once, that the repo's tests for each changed file must pass (some pin a prompt's wording), and that the work is done when that `--verify` command exits 0.
- **Otherwise**, make the edit yourself in the worktree: change the code that builds the prompt so its output holds the new text, keeping every placeholder's code as it is. Then run the repo's tests for each changed file, and update any test that pins the old wording.

Then run the `--verify` command. On exit 1 it names a case whose request doesn't hold the candidate exactly once. Fix the edit and verify again.

Done when `--verify` exits 0 and the repo's tests for the changed files pass.

## 4. Hand back

Tell the user, in a few lines:
- the branch (or the folder, with `git apply <folder>/change.patch` to use it);
- the run it came from, and its held-back result;
- that nothing was pushed, and that merging is theirs to do;
- for a workspace outside the repo, that init's editable step must be rerun after merging.
