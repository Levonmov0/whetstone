---
name: checks
description: Turn left-swipe reasons that no check covers into proposed code checks or judge rubrics, add only the ones the user approves, then measure the judges against the swipes.
disable-model-invocation: true
---

Grow a prompt's checks from what graders complained about. The check and rubric formats are in `${CLAUDE_PLUGIN_ROOT}/docs/workspace.md`. Read it first.

The engine is `whetstone` on the Bash tool's PATH. Run it from the workspace folder, or pass `--workspace`.

## 1. What no check covers yet

```bash
whetstone reasons <prompt>
```

It lists every left-swipe reason, and every note left without a reason, that no existing check stands for, most frequent first. With `every reason has a check`, tell the user and stop.

For each line, read the swiped outputs behind it in `labels.jsonl`, plus each real-data source's `cases/private/<source>/labels.jsonl`. Read the notes too: they say why in the grader's own words.

Done when you can say, for each reason, what the outputs it was given for have in common.

## 2. Propose

One check per rule, never one check for several rules. Write each into `checks/proposed/`. The engine never runs anything there.

- **Code check** (`checks/proposed/<name>.py`) whenever code can decide it: length, banned words, structure, placeholders, a pattern. It's free, fast and exact. `check(output)` returns one message per broken rule, and an empty list when it passes. Start the file with `REASONS = ["…"]`, the swipe reasons it stands for, including the exact one from step 1, so `whetstone reasons` counts them as covered.
- **Judge** (`checks/proposed/<name>.judge.toml`) only when code can't decide it: voice, implied causation, invented facts, what the reads already covered. A judge costs one OpenAI call per case on every run.
  - `question` asks one thing about the output. The judge sees the case input as context.
  - `pass` is the answer that means the output is fine.
  - Each entry under `[fail]` is a failing answer, and its value is the reason shown, written the way a grader would say it. Use two answers for a binary question, more for multiple choice.
  - `reasons` lists the swipe reasons this judge stands for, including the exact one from step 1. It sits above `[fail]`, since TOML puts every key after `[fail]` inside it.
  - `guide` (optional) gives the detail the question needs: what counts and what doesn't, with a good and a bad example taken from the swipes.

For each judge, also add its reason to `prompt.toml`'s `reasons` list if it isn't there yet. On a card only a judge caught, the app still asks why, so graders tap it there and on later swipes. Only swipes that name the rule count when the judge is measured.

Done when every line from step 1 has one proposal, or a sentence saying why it shouldn't become a check (a one-off, or a taste call the user should make).

## 3. Review with the user

Show each proposal: its name, whether it's code or a judge, the rule in one sentence, and the full file. Then ask the user to keep, edit or delete each one.
- **Keep:** move it from `checks/proposed/` to `checks/`.
- **Edit:** change it as asked, show the result, then move it.
- **Delete:** delete the file.

Nothing enters `checks/` without the user's yes. When the review ends, delete what is left in `proposed/`.

Done when `proposed/` is empty and `whetstone reasons <prompt>` no longer lists the reasons the kept checks stand for.

## 4. Measure the judges

With a judge in `checks/`, the workspace needs `JUDGE_API_KEY` in `<ws>/.env` and `[models] judge = { provider = "openai", model = "…" }` in `whetstone.toml`. Ask the user to paste the key in themselves. Never read, print or write its value. Check that it's there with `grep -cE '^(export )?JUDGE_API_KEY *= *[^ ]' <ws>/.env`.

```bash
whetstone agreement <prompt>
```

It judges every swiped card once (one OpenAI call per card per judge, printed before it starts). For each judge and each grader, it shows how often the judge agreed: on cards they called good, and on cards they called bad for that judge's rule.
- **trusted:** 90% or more on both sides.
- **warn:** 80% to 90%.
- **untrusted:** below 80% on either side, or fewer than 5 swipes on a side. The optimizer (`/whetstone:run`) refuses to run against an untrusted judge.

For each untrusted judge, follow its advice:
- "fails outputs … called good": the judge is too strict. Sharpen `guide` with the good outputs it failed, then run `agreement` again.
- "misses problems … flagged": the judge is too lenient. Sharpen `guide` with the bad outputs it passed, or swipe more examples.
- "only N … swipes": run `whetstone check <prompt>` and `/whetstone:grade` for more swipes, tapping the judge's reason on bad cards.

Done when every judge is trusted or warned, or the user decides to drop the ones that aren't.
