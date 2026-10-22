# GEPA trial result (2026-10-22)

Cheap trial: Haiku 5.5 writes the cards, Sonnet 5.5 rewrites the prompt. Kin's "YOUR JOB TODAY" block was the only text it could change, scored on 10 code checks taken from Kin's written format rules. Budget: 150 card generations. 18 rounds, 7 prompt versions kept.

## Held-out (10 cases GEPA never saw, 2 tries each)

| | Original prompt | GEPA's prompt |
|---|---|---|
| Cards passing every rule | 15% | **65%** |
| Average score | 0.88 | **0.94** |
| Paragraphs over 40 words | 22 | 3 |

Noise floor: the same unchanged prompt scored 0.90 and 0.87 on two runs, so the gain is well above chance.

**Cost:** 214 model calls, 1.52M tokens in, 131k out, roughly $1–1.50.

## What it did to the prompt

409 → 1,275 words: [runs/best_job.txt](runs/best_job.txt). It's structured and readable, but it shows each risk from HANDOFF.md:

- **Unchecked things drifted.** The tone line now says "warm, coach-like". Kin's core prompt says "not a wellness app, life coach". It also suggests "breathing, grounding" and quotes numbers in an example ("energy 9 versus 4-6"), which Kin's rules ban. None of that is in the 10 checks, so GEPA had no reason to protect it.
- **Rules written for specific training cases.** It added "don't assume a weigh-in or weight cut", "the room/court" and "last four sessions when there are five". Each one patches a single training case.
- **The test feedback ended up in the prompt.** It says "Past failures were paragraphs of 42, 43, 45, and 53 words".

## Verdict

GEPA works: it moved a real prompt toward its tests on unseen cases, cheaply. But it only protects what is tested. Anything unchecked, especially voice, can get worse while the score rises. A real run therefore needs voice and grounding checks (judges calibrated against human grades) in the suite, and a person must read the final prompt before promoting it.
