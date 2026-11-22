---
name: grade
description: Start the Whetstone swipe app for a prompt, show its QR code, and settle cards graders disagree on.
disable-model-invocation: true
---

Get a prompt's outputs graded on phones, then settle disagreements. The workspace layout is in `${CLAUDE_PLUGIN_ROOT}/docs/workspace.md`.

The engine is `whetstone` on the Bash tool's PATH. Run it from the workspace folder, or pass `--workspace`.

## 1. Reason chips

If the prompt's `prompt.toml` has no `reasons` list, propose four to eight short reasons from the repo's voice and copy rules and the checks that already exist ("too long", "sounds like a robot", "makes a medical claim"). Skip reasons an existing check already catches: the app asks nothing more for those. Add the list the user approves as `reasons = [...]`.

## 2. Cards

The app shows the outputs from the latest `whetstone check <prompt>` run. If there is none yet (no `.whetstone/decks/<prompt>.json`), or the cases or prompt changed since, run `whetstone check <prompt>` first. It calls the production model once per case; say so before running it.

## 3. Server

```bash
whetstone serve <prompt>
```

It returns at once and leaves the server running in the background, even after this session ends. It stops itself 12 hours after it started, whatever graders are doing, or with `whetstone serve --stop`. Running it again while it's up shows the same link. Tell graders it closes at that time; their swipes are saved as they go.

Show the user the QR code and the link from its output, in a code block so the QR keeps its shape. Tell them:
- Phones must be on the same Wi-Fi as this laptop, or on Tailscale when `whetstone.toml` says `phone.access = "tailscale"`.
- Each grader enters their name once. Right is good, left is bad, up is skip; the buttons do the same.
- A new token is made each time the server starts, so an old QR code stops working.

If it exits 2, show the message and fix what it names. With no Wi-Fi address, ask whether to use Tailscale; never suggest a public tunnel.

## 4. Match notes as they land

Graders mostly say what's wrong in a note instead of tapping a chip, and a note counts toward a check only once it is matched to that check's reason. Right after the server is up, without asking, start the live matching with the Monitor tool:

```bash
whetstone notes <prompt> --follow
```

It prints every unmatched note first, then each new one about a second after the grader saves it, one JSON line each: `swipe`, `grader`, `card`, `note`, the `reasons` already tapped, and an `excerpt` of the output. It runs until stopped. For each line, compare the note with the reasons the checks stand for: each code check's `REASONS`, and each judge's `question`, `guide`, `[fail]` answers and `reasons` (in `checks/`). Then record one match, or none:

```bash
whetstone map <prompt> <swipe> --reasons "<reason>" ["<reason>" …] --sure|--ask --why "<one line>"
```

- **Sure** (`--sure`): the note names the exact thing a judge's question, guide or failing answer describes, or a code check's reason ("Says HRV and sleep latency" when banned terms list HRV). It counts at once. The grader sees it under "Claude matched N more on its own" and can undo it.
- **Ask** (`--ask`): anything that needs interpretation, such as a paraphrase, an inference, or a note that could mean two things ("Tells me to take it easy, but I said I slept great" for "ignores check-in"). It goes to the grader's phone, and only the grader answers it. Never answer an ask for the grader, and never tell the user what the grader meant.
- **No match:** the note says something no check stands for. Record nothing. `/whetstone:checks` turns it into a new check later.
- A note that names two problems gets both reasons in one `map`, if both are sure. If either one is a judgement call, use `--ask`.
- `--reasons` takes reasons exactly as the checks spell them. `--why` is one line the grader will read beside the suggested chip.

`map` prints `counted`, `waiting` or `refused` with why. A refusal is not an error. `swiped … again` means a newer swipe replaced the note, and its note arrives as its own line. `already matched` means another session got there first. Go on to the next line. Don't print each match to the user. When grading ends, say how many notes were counted, how many wait on graders and how many matched nothing.

If undos pile up on sure matches (`whetstone agreement` shows the undone column), be stricter about sure.

## 5. Settle disagreements

When the user says grading is done, stop the Monitor, then run `whetstone disagreements <prompt>`. For each card it lists, show the output (from the labels, or `.whetstone/decks/<prompt>.json`), each grader's verdict, reasons and note, and ask the user for their call. Then record it:

```bash
whetstone settle <prompt> <card-id> good|bad --grader "<user's name>" --note "<the rule, in their words>"
```

A disagreement usually means an unwritten rule. Ask the user to say it in one sentence, and put that in `--note`.

Done when `whetstone disagreements <prompt>` prints `nothing to settle`. Then tell the user how many cards were graded and by whom, and that `/whetstone:checks` turns the left-swipe reasons into checks next.
