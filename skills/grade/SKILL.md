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

It returns at once and leaves the server running in the background, even after this session ends. It stops itself after 12 hours without a swipe, or with `whetstone serve --stop`. Running it again while it's up shows the same link.

Show the user the QR code and the link from its output, in a code block so the QR keeps its shape. Tell them:
- Phones must be on the same Wi-Fi as this laptop, or on Tailscale when `whetstone.toml` says `phone.access = "tailscale"`.
- Each grader enters their name once. Right is good, left is bad, up is skip; the buttons do the same.
- A new token is made each time the server starts, so an old QR code stops working.

If it exits 2, show the message and fix what it names. With no Wi-Fi address, ask whether to use Tailscale; never suggest a public tunnel.

## 4. Settle disagreements

When the user says grading is done, run `whetstone disagreements <prompt>`. For each card it lists, show the output (from the labels, or `.whetstone/decks/<prompt>.json`), each grader's verdict, reasons and note, and ask the user for their call. Then record it:

```bash
whetstone settle <prompt> <card-id> good|bad --grader "<user's name>" --note "<the rule, in their words>"
```

A disagreement usually means an unwritten rule. Ask the user to say it in one sentence, and put that in `--note`.

Done when `whetstone disagreements <prompt>` prints `nothing to settle`. Then tell the user how many cards were graded, by whom, and that the next step is turning the left-swipe reasons into checks.
