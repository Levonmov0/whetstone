# GEPA spike: Kin's Today insight prompt

Written 2026-10-21. A throwaway experiment, not the product. Nothing here becomes the plugin; it only decides whether the plugin is worth building.

## The question

Does GEPA turn Levon's own judgement into a prompt whose outputs he prefers, on cases it never trained on, while the prompt stays readable? It runs in the order the product would:

1. **Grade today's prompt.** 30 made-up athlete cases go through the real production prompt. Levon marks each output good or bad, with a one-line reason when it's bad.
2. **Reasons become tests.** Each reason becomes a check: code where possible, an AI judge where not. A judge only counts once it agrees with Levon's grades.
3. **GEPA runs** on 18 cases. The other 12 are held back, and GEPA never sees them or the checks.
4. **Grade blind.** On the 12 held-back cases, old and new outputs are shuffled together and Levon grades them without knowing which is which.

**It works if** Levon picks the new prompt clearly more often on held-back cases, and the new prompt still reads like something a person would maintain. Record the number of model calls and the cost.

## Rules

- **Mono is read-only.** Everything lives in `whetstone/spike/`. Kin's prompt builder, sanitizer and schema are imported from `~/Developer/mono` by path and run in place. Nothing is written there.
- **Same model as production:** `claude-opus-5`, the Anthropic default tier. Judges run on OpenAI, a different family.
- **No real athlete data.** All cases are invented.
- **GEPA edits only the "YOUR JOB TODAY" block.** The rest of the system prompt is shared with other Kin prompts.
- **Grading is crude:** a markdown file with ✅ or ❌ and a reason. No UI.

## Decided

- 2026-10-21: production runs `claude-opus-5`.
- 2026-10-21: mono gets no files, branches or worktrees.
- 2026-10-21: no causal-word ban for Today. The prompt asks for "why today looks the way it does". If unsupported causes come up in grading, they become a test then.
