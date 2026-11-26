---
name: checks
description: Turn left-swipe reasons that no check covers into proposed code checks or judge rubrics, add only the ones the user approves, then measure the judges against the swipes.
disable-model-invocation: true
---

Grow a prompt's checks from what graders complained about. The check and rubric formats are in `${CLAUDE_PLUGIN_ROOT}/docs/workspace.md`. Read it first.

The engine is `whetstone` on the Bash tool's PATH. Run it from the workspace folder, or pass `--workspace`.

## 1. Match the backlog

A note can name a rule some check already stands for. Match those first, so only truly new reasons become checks:

```bash
whetstone notes <prompt>
```

It prints each unmatched note as a JSON line: `swipe`, `grader`, `card`, `note`, the `reasons` already tapped, and an `excerpt` of the output. Compare each note with the reasons the checks stand for: each code check's `REASONS`, and each judge's `question`, `guide`, `[fail]` answers and `reasons`. Then record one match, or none:

```bash
whetstone map <prompt> <swipe> --reasons "<reason>" ["<reason>" …] --sure|--ask --why "<one line>"
```

- **Sure** (`--sure`): the note names the exact thing a judge's question, guide or failing answer describes, or a code check's reason. It counts at once, and the grader can undo it in the app.
- **Ask** (`--ask`): anything that needs interpretation, such as a paraphrase, an inference, or a note that could mean two things. It waits for the grader in the swipe app. Never answer it for the grader, even when the user is the one running this.
- **No match:** the note says something no check stands for. Record nothing, and it becomes an idea in step 2.
- A note that names two problems gets both reasons in one `map`. If either one is a judgement call, use `--ask`.

`map` prints `counted`, `waiting` or `refused` with why. `refused` (a newer swipe, or another session got there first) needs nothing from you.

Done when every line `notes` printed has a match or a reason it has none.

## 2. What no check covers yet

```bash
whetstone reasons <prompt>
```

It lists every left-swipe reason, and every note left without a reason, that no existing check stands for, most frequent first. Notes a match counts, and notes waiting on their grader, are left out. A note the grader answered No to is listed with its swipe id (`note: "…" · s_…`). Propose new checks only from what this lists. With `every reason has a check`, tell the user and stop.

For each line, read the swiped outputs behind it in `labels.jsonl`, plus each real-data source's `cases/private/<source>/labels.jsonl`. Read the notes too: they say why in the grader's own words.

Done when you can say, for each reason, what the outputs it was given for have in common.

## 3. Propose

One check per rule, never one check for several rules. Write each into `checks/proposed/`. The engine never runs anything there.

- **Code check** (`checks/proposed/<name>.py`) whenever code can decide it: length, banned words, structure, placeholders, a pattern. It's free, fast and exact. `check(output)` returns one message per broken rule, and an empty list when it passes. Start the file with `REASONS = ["…"]`, the swipe reasons it stands for, including the exact one from step 2, so `whetstone reasons` counts them as covered.
- **Judge** (`checks/proposed/<name>.judge.toml`) only when code can't decide it: voice, implied causation, invented facts, what the reads already covered. A judge costs one OpenAI call per case on every run.
  - `question` asks one thing about the output. The judge sees the case input as context.
  - `pass` is the answer that means the output is fine.
  - Each entry under `[fail]` is a failing answer, and its value is the reason shown, written the way a grader would say it. Use two answers for a binary question, more for multiple choice.
  - `reasons` lists the swipe reasons this judge stands for, including the exact one from step 2. It sits above `[fail]`, since TOML puts every key after `[fail]` inside it.
  - `guide` (optional) gives the detail the question needs: what counts and what doesn't, with a good and a bad example taken from the swipes.
  - **Keep the guide to the question's one rule.** A second rule slips in most easily as one more "wrong" bullet or example. Test every failing case in the guide: fix only what the question asks about (for a timing judge, move the line to the right moment) and ask whether it would now pass. If it would still fail, it fails for another rule. Take it out, and propose that rule as its own check. Example: a morning-timing guide that also failed "asks whether a task got done" failed "Did you put the phone down last night?" at exactly the right time, so it judged two rules and disagreed with the grader on the second.

For each judge, also add its reason to `prompt.toml`'s `reasons` list if it isn't there yet. On a card only a judge caught, the app still asks why, so graders tap it there and on later swipes. Only swipes that name the rule count when the judge is measured.

Done when every line from step 2 has one proposal, or a sentence saying why it shouldn't become a check (a one-off, or a taste call the user should make).

## 4. Review with the user

Show each proposal: its name, whether it's code or a judge, the rule in one sentence, and the full file. Then ask the user to keep, edit or delete each one.
- **Keep:** move it from `checks/proposed/` to `checks/`.
- **Edit:** change it as asked, show the result, then move it.
- **Delete:** delete the file.

Nothing enters `checks/` without the user's yes. When the review ends, delete what is left in `proposed/`.

Then, for each kept check written from notes, match those notes against it, as in step 1 but against the new check only. Take the swipe ids from `whetstone notes <prompt>` and, for notes answered No, from the ids `whetstone reasons` printed in step 2. Sure or ask follow the same rules. `map` refuses a reason the grader already said No to (`answered No to "…"`), so never offer them the same reason twice.

Done when `proposed/` is empty, each kept check's source notes are matched or left as ideas, and `whetstone reasons <prompt>` no longer lists the reasons the kept checks stand for.

## 5. Measure the judges

With a judge in `checks/`, the workspace needs `JUDGE_API_KEY` in `<ws>/.env` and `[models] judge = { provider = "openai", model = "…" }` in `whetstone.toml`. Ask the user to paste the key in themselves. Never read, print or write its value. Check that it's there with `grep -cE '^(export )?JUDGE_API_KEY *= *[^ ]' <ws>/.env`.

```bash
whetstone agreement <prompt>
```

It judges every swiped card once (one OpenAI call per card per judge, printed before it starts). For each judge and each grader, it shows how often the judge agreed: on cards they called good, and on cards they called bad for that judge's rule.
- **trusted:** 90% or more on both sides.
- **warn:** 80% to 90%.
- **unmeasured:** the good side is measured (5 or more swipes, at least 80%), but the bad side has fewer than 5 swipes. The prompt rarely breaks this rule, so nobody has seen the judge catch it. The optimizer runs against it and warns that it guards the run untested.
- **untrusted:** below 80% on a side with 5 or more swipes, or fewer than 5 good swipes. The optimizer (`/whetstone:run`) refuses to run against an untrusted judge.

A side with fewer than 5 swipes is unmeasured, not failed.

For each untrusted judge, follow its advice:
- "fails outputs … called good": the judge is too strict. Read the good outputs it failed side by side. If what they share has nothing to do with the question (they are all yes/no, all long), the guide carries a second rule: remove it as in step 3, and propose that rule as its own check. Otherwise sharpen `guide` with those outputs. Then run `agreement` again.
- "misses problems … flagged": the judge is too lenient. Sharpen `guide` with the bad outputs it passed, or swipe more examples.
- "only N good swipes": run `whetstone check <prompt>` and `/whetstone:grade` for more swipes.

For each unmeasured judge, tell the user it guards the run untested. Offer cases built to tempt the prompt into breaking the rule (`/whetstone:cases`), then a round of swipes tapping the judge's reason on bad cards. If the prompt still never breaks it, the user may run anyway: the run and `apply` name the judge.

Done when every judge is trusted, warned or unmeasured with the user's go-ahead, or the user decides to drop the ones that aren't.
