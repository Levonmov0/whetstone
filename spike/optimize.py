# /// script
# requires-python = ">=3.12"
# dependencies = ["gepa==0.1.4", "anthropic", "tqdm", "python-dotenv"]
# ///
"""Quick GEPA check: can it rewrite Kin's "YOUR JOB TODAY" block so outputs obey
Kin's own written format rules, on cases it never saw?

Checks are code only (rules quoted from mono's sharedRules.ts / insightPrompt.ts),
so no grader to calibrate. Run spike/export.ts first.

  uv run spike/optimize.py [budget]
"""

import json
import random
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic
import gepa
from dotenv import load_dotenv

# Whetstone's own key, not Kin's backend key: one secret per purpose.
load_dotenv(Path(__file__).parent.parent / ".env")

# Trying GEPA itself, not tuning Kin: cheap models by default (~$1 a run).
# For a real tuning run, match production: TASK_MODEL=claude-opus-5.
import os
MODEL = os.environ.get("TASK_MODEL", "claude-haiku-5-5")
REFLECT_MODEL = os.environ.get("REFLECT_MODEL", "claude-sonnet-5-5")
RUNS = Path("spike/runs")
parts = json.loads((RUNS / "prompt_parts.json").read_text())
# Pinned: a Claude Code shell exports ANTHROPIC_BASE_URL for its own endpoint.
client = anthropic.Anthropic(base_url="https://api.anthropic.com", max_retries=4)
TOOL = {
    "name": "structured_response",
    "description": "Return a structured response matching the required schema",
    "input_schema": parts["inputSchema"],
}

usage = {"calls": 0, "in": 0, "out": 0}
lock = threading.Lock()


def track(r):
    with lock:
        usage["calls"] += 1
        usage["in"] += r.usage.input_tokens
        usage["out"] += r.usage.output_tokens


def generate(case, job):
    r = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=case["system"],
        messages=[{"role": "user", "content": case["userPrefix"] + job}],
        tools=[TOOL],
        tool_choice={"type": "tool", "name": TOOL["name"]},
    )
    track(r)
    return next(b.input for b in r.content if b.type == "tool_use")


# ── checks: Kin's own written rules ─────────────────────────────────────────
BANNED = re.compile(
    r"\b(HRV|heart rate variability|RHR|resting heart rate|sleep stages?|REM|deep sleep|wearables?|trackers?|sensors?|smartwatch(?:es)?|fitness tracker|sleep tracker)\b",
    re.I,
)
STYLE = re.compile(r"not just\b.*\bbut\b|that said|to that end|at its core|it is worth noting", re.I)
words = lambda s: len(s.split())
paras = lambda s: [p.strip() for p in re.split(r"\n\s*\n", s) if p.strip()]
sents = lambda p: len([s for s in re.split(r"(?<=[.!?])\s+", p) if s])


def check(o):
    """Returns a list of failure messages; empty means every rule held."""
    f = []
    text = "\n".join([o["title"], o["summary"], o["meaning"], o["try"], *o["tags"]])
    if "—" in text:
        f.append("Uses an em dash (rule: never use em dashes).")
    if m := BANNED.search(text):
        f.append(f'Uses banned biometric term "{m.group(0)}".')
    if m := STYLE.search(text):
        f.append(f'Uses banned stock phrase "{m.group(0)}".')
    if re.search(r"\d", " ".join([o["title"], o["summary"], o["meaning"], o["try"]])):
        f.append("Cites a number (rule: do not cite raw numbers; use high, low, steady).")
    if words(o["summary"]) > 25:
        f.append(f"Summary is {words(o['summary'])} words (max 25).")
    if not 2 <= len(o["tags"]) <= 4 or any(t != t.lower() or words(t) > 3 for t in o["tags"]):
        f.append(f"Tags {o['tags']} break the rule: 2-4 tags, lowercase, max 3 words each.")
    mp = paras(o["meaning"])
    if not 2 <= len(mp) <= 3:
        f.append(f"Meaning has {len(mp)} paragraphs (must be 2-3, separated by blank lines).")
    for i, p in enumerate(mp, 1):
        if sents(p) > 2:
            f.append(f"Meaning paragraph {i} has {sents(p)} sentences (max 2).")
        if words(p) > 40:
            f.append(f"Meaning paragraph {i} has {words(p)} words (max 40).")
    if len(paras(o["try"])) > 2:
        f.append(f"Try has {len(paras(o['try']))} paragraphs (max 2).")
    return f


N_CHECKS = 10  # rule families above; score = share of them held


def score(fails):
    families = {re.sub(r"\d+", "#", x.split(" (")[0].split('"')[0]) for x in fails}
    # one failing family costs one point however many paragraphs break it
    families = {re.sub(r"paragraph #", "paragraph", x) for x in families}
    return max(0.0, 1 - len(families) / N_CHECKS)


def run_case(case, job):
    try:
        out = generate(case, job)
        fails = check(out)
    except (StopIteration, KeyError, TypeError, AttributeError) as e:  # model output unusable; API errors stop the run
        out, fails = None, [f"No valid output: {e}"]
        return out, 0.0, fails
    return out, score(fails), fails


# ── GEPA adapter ────────────────────────────────────────────────────────────
class Adapter(gepa.GEPAAdapter):
    def evaluate(self, batch, candidate, capture_traces=False):
        with ThreadPoolExecutor(8) as ex:
            res = list(ex.map(lambda c: run_case(c, candidate["today_job"]), batch))
        return gepa.EvaluationBatch(
            outputs=[r[0] for r in res],
            scores=[r[1] for r in res],
            trajectories=[{"case": c, "out": r[0], "fails": r[2]} for c, r in zip(batch, res)] if capture_traces else None,
        )

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        rows = [
            {
                "Inputs": t["case"]["userPrefix"].split("\nRelevant principles")[0][:1500],
                "Generated Outputs": json.dumps(t["out"], indent=1) if t["out"] else "none",
                "Feedback": "All rules held." if not t["fails"] else "Broke these rules:\n- " + "\n- ".join(t["fails"]),
            }
            for t in eval_batch.trajectories
        ]
        return {k: rows for k in components_to_update}


def reflect(prompt) -> str:
    messages = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else prompt
    r = client.messages.create(model=REFLECT_MODEL, max_tokens=8000, messages=messages)
    track(r)
    return "".join(b.text for b in r.content if b.type == "text")


def held_out(cases, job, trials=2):
    rows = [run_case(c, job) for c in cases for _ in range(trials)]
    rate = sum(1 for r in rows if not r[2]) / len(rows)
    fails = [f for r in rows for f in r[2]]
    return rate, sum(r[1] for r in rows) / len(rows), fails


if __name__ == "__main__":
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    cases = parts["cases"][:]
    random.Random(7).shuffle(cases)
    train, val, test = cases[:12], cases[12:20], cases[20:]
    seed = {"today_job": parts["seedJob"]}

    result = gepa.optimize(
        seed_candidate=seed,
        trainset=train,
        valset=val,
        adapter=Adapter(),
        reflection_lm=reflect,
        reflection_minibatch_size=3,
        max_metric_calls=budget,
        run_dir=str(RUNS / "gepa"),
        display_progress_bar=True,
    )
    if result.num_candidates < 2:
        sys.exit("GEPA never proposed a new prompt; check the log for reflection errors.")
    best = result.best_candidate["today_job"]
    (RUNS / "best_job.txt").write_text(best)
    opt_usage = dict(usage)

    report = {"split": {"train": [c["id"] for c in train], "val": [c["id"] for c in val], "test": [c["id"] for c in test]}}
    for name, job in [("seed", seed["today_job"]), ("best", best)]:
        rate, avg, fails = held_out(test, job)
        report[name] = {"all_rules_held": rate, "avg_score": avg, "failures": fails}
        print(f"\nHELD-OUT {name}: {rate:.0%} of outputs held every rule, avg score {avg:.2f}")
        for x in sorted(set(fails)):
            print("  -", x)
    report["usage"] = {"optimize": opt_usage, "total": usage}
    (RUNS / "report.json").write_text(json.dumps(report, indent=2))
    print("\nusage:", report["usage"])
