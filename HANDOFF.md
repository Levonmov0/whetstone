# Whetstone — handoff

Written 2026-10-21. Whetstone does not exist yet. This file is the brief for the session that starts it.

## The idea

Nobody hand-tunes prompts. Tests are the only thing a person writes. An optimizer (GEPA) rewrites the prompt until every test passes.

The problem it solves: prompt work today means tweaking for ages, building evals afterwards, and still ending up tuning on vibes. Whetstone flips the order. First write what the prompt must and must never do, as failing tests. Then let the optimizer find the prompt.

It's TDD for prompts:

- **Red:** a failing test, made of one input and one pass/fail check.
- **Green:** GEPA rewrites the prompt until the whole suite passes, including held-out cases it never trained on.
- A person reviews the diff and promotes the prompt. Nothing auto-ships.

## Two entry points, one pipeline

**Fixing an existing prompt.** A bad output turns into a failing test, and GEPA reruns. That is the whole loop.

**A new feature that needs a prompt.**

1. **Interview** (in Claude Code, after reading the repo, so questions start from what the repo already says): what the prompt is for, when it runs, what input it gets, what the output looks like, what must never happen. Each answer becomes a test card, shown live beside the chat.
2. **Example inputs:** Whetstone suggests 20–30 realistic and edge-case inputs as cards. The user keeps, edits or deletes each one, or uploads their own. Nothing is added without approval.
3. **Seed prompt:** drafted from best practices, the project's docs and voice rules, and its codebase context (data contracts, available inputs). GEPA polishes wording but won't invent structure, so the seed has to have the right inputs and output shape.
4. **Swipe grading:** each output is shown as a card in the repo's own swipe app (built by `/whetstone:init`, see below), opened on a phone.
   - **Right:** good.
   - **Left:** bad. If an existing check already catches the problem, nothing more is asked. Otherwise quick reason chips appear, plus "other" for a one-line or voice note. A new reason becomes a new test.
   - **Up:** unsure, skip.
5. **Improve:** GEPA runs. The UI shows plain progress, such as "17 of 20 checks passing". When it gets stuck, it explains why in plain words: "these two rules conflict", or "this needs more input data".
6. **Done:** the final prompt, what changed and why, and the list of rules it passes, committed in the repo as a `candidate`. Sending it on to Langfuse or similar is the repo's own business.

**Key design point:** the swipes are the human labels. They are also what the AI graders get checked against, so validating a grader costs nothing extra.

## Product decisions made

- **A Claude Code plugin** (decided 2026-10-21), not a web app. It runs inside whatever repo it's used in, so "connect your repo" is free: it reads existing prompts, voice and copy guidelines, schemas and call sites before grilling the user and before drafting the seed prompt. Users bring their own model keys, and data never leaves their machine. No login, billing or per-team isolation to build.
- **Standalone, no Switchyard** (decided 2026-10-22). Whetstone is its own plugin and is not designed around Switchyard. A Switchyard hook may be added later as its own piece.
- **Not Kin-only.** Kin is the first user.
- **Build on GEPA as a dependency** (decided 2026-10-22, after the spike in `spike/RESULTS.md`). Don't rebuild it or any part of it. Pin the version, and reach GEPA only through `gepa.optimize(...)` and our adapter. Its options (reflection template, selection, acceptance, stop rules) cover what we need. After v1: replace GEPA's default reflection instructions. Today they tell the model to copy "all niche and domain specific factual information" into the prompt, which bloated our prompt with case-specific rules. Ours should forbid that and protect the voice rules.
- **Developers first.** Users are Claude Code users. Non-developers are out of scope for now.
- **One swipe app, themed per repo** (revised 2026-10-22). Whetstone ships one swipe app; `/whetstone:init` extracts the repo's design tokens into a theme, falling back to Whetstone's own. The phone opens it over the local network. Swipes are written back as labels.
- **Never auto-promote.** Whetstone stops at a `candidate` prompt, and a person promotes it.
- **v1 design:** settled in a grilling session on 2026-10-22. The full decision set is the v1 spec: https://github.com/Levonmov0/whetstone/issues/1

## Open decisions

None. All earlier open decisions were settled on 2026-10-22; see the v1 spec issue.

## First step: prove the GEPA loop, with no UI

The UI is known work. The open question is whether GEPA reliably turns a suite green without regressions on a real prompt. Prove that first, on **Kin's daily-insight prompt** ("Today insight"). It's the best test case because the voice and no-causal-claims rules matter most there.

Where it lives in the Kin repo (`~/Developer/mono`; read `docs/llm-prompt-inventory.md` §1 first):

- **Builder:** `buildInsightPrompt({ mode: "TODAY" })` in `apps/backend/src/domain/ai/prompts/insightPrompt.ts`, assembled by `domain/ai/buildTodayInsightContext.ts`.
- **Shared prompt parts:** `domain/ai/prompts/{corePrompt,contextBlock,sharedRules,frameworkKnowledge}.ts`.
- **Output schema:** `InsightOutputSchema` in `packages/contracts/src/insight.ts`.
- **Post-processing:** `sanitizeInsightCard`, plus `domain/ai/bannedTerms.ts`.
- **Voice rules:** `docs/VOICE_AND_COPY_GUIDELINES.md`.
- **Langfuse:** Kin already manages prompts, datasets, scores and experiments there.

Spike plan:

1. **Tests:** 20–40 cases built from Kin fixtures and fake-backend data, covering edge cases such as no wearable, first day and conflicting signals. **No real athlete or prod data** without Levon's explicit yes.
2. **Checks:**
   - **Code first:** the output parses against the Zod schema (mirrored as JSON Schema), banned and causal terms ("because", "caused", "led to", "due to"), and length.
   - **AI graders only for what code can't decide:** implied causation, voice. Binary pass/fail, one grader per criterion, from a different model family than the generator.
3. **Grader calibration:** Levon labels about 50–100 outputs pass/fail. Each grader must agree with those labels at least 90% of the time (80% is the floor) on passes and on fails, measured on a held-out split.
4. **Optimizer:** a Python script using standalone GEPA (`pip install gepa`, `optimize_anything`). It seeds from the current prompt, and the evaluator returns a score plus the failure reasons. The task model and parameters must match production. Split the cases into train and held-out, and never let the optimizer see the held-out ones or edit the checks.
5. **Write-back:** the winning prompt goes into Langfuse as a new version labelled `candidate`. A Langfuse experiment (in TypeScript, `langfuse.experiment.run`) is the gate before anyone moves the `production` label.
6. **Success means:**
   - the suite goes green;
   - held-out results don't drop;
   - the prompt is still readable;
   - one new failing test can be added and turned green again without regressions.
   - Record what each run cost in model calls.

Kin rule: nothing in the Kin app changes for this. Python is a dev-time tool only.

## Research summary (2026-10-21)

Five research passes covered optimizers, hosted platforms, tools for writing evals from intent, CLI and agent tools, and TypeScript fit. Findings came from web search and were only partly checked against primary sources.

- **No product does the whole loop** (intent → tests → graders → automatic rewrite). That gap is Whetstone.
- **GEPA** (github.com/gepa-ai/gepa, about 7.1k stars, v0.1.4, ICLR 2026 oral, arXiv 2507.19457) is the best optimizer. Three of the five passes chose it independently. It works from 3+ examples, takes roughly 100–500 evaluations per run, and supports Anthropic and OpenAI through LiteLLM. Its output is a readable prompt. Being pre-1.0, its API may shift. `dspy.GEPA` is the same engine but requires restructuring code into DSPy.
- **Langfuse** has no optimizer, only evals, experiments and prompt versions. Its own suggested loop (blog post, 2026-02-16) is Claude plus a Langfuse skill, approved by a person. ClickHouse acquired Langfuse in January 2026.
- **Alternatives that bundle both halves:**
  - **Opik** (Comet): open source, self-hostable, includes GEPA.
  - **Arize AX:** hosted "Prompt Learning".
  - **Braintrust Loop:** writes graders from intent but stops for approval at each step.
  - Using any of the hosted ones would send athlete data to another vendor.
- **Dead or avoid:** Humanloop (shut down 2025-09), Vellum (pivoted), LangChain promptim (abandoned), OpenAI Evals dashboard (possibly shutting down 2026-11-30, unverified). promptfoo was acquired by OpenAI in March 2026; it's still open source but has no optimizer.
- **TypeScript:** Ax (ax-llm/ax, about 3k stars) supports GEPA but needs LLM calls rewritten as Ax signatures. Evalite and Langfuse experiments work as test runners only. There is no official TypeScript port of GEPA.
- **Prior art for the interview and grading step:** EvalGen (Shankar et al., UIST 2024, "Who Validates the Validators?", arXiv 2404.12272) and Hamel Husain / Shreya Shankar's method: error analysis first, binary judges, graders validated against human labels. There is also a community skill, `hamelsmu/evals-skills`. Sentry reportedly has a "prompt-optimizer" agent skill running a similar loop (unverified).

## Known risks

- **You can't fully define tests up front.** People only work out what "good" means by grading real outputs ("criteria drift", the EvalGen paper's main finding). That's why the swipe step sits inside the new-prompt flow, before tests are frozen.
- **Overfitting.** Simon Willison's GEPA run in July 2026 raised train accuracy from 90% to 95% while held-out accuracy dropped from 95% to 85%, because the optimizer stacked conflicting rules into the prompt. Held-out cases and a human read of the final prompt are both required.
- **Graders get gamed.** An uncalibrated grader, or one that shares a model with the generator, will be optimized against. Calibrate graders, keep the checks read-only for the optimizer, and use a different model family.
- **Tone is the hardest part.** Optimizers fix checkable failures well. Voice only improves once the voice rules are written as binary checks.
- **Conflicting tests.** When GEPA can't get to green, it usually means two tests contradict each other, or the fix needs a better model or more input data rather than a better prompt. Surface this as a result in its own right, not as a failure.
