"""The live smoke run: real cheap models, about $0.10. Not in `make check`; run it with `make smoke`. It needs
SMOKE_GENERATION_API_KEY in the repo's .env, and Claude Code logged in for the rewrites."""

import json
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

from whetstone.entry.cli import production_model, run

ROOT = Path(__file__).parent.parent
HARNESS = (
    "import json, sys\n"
    "case = json.load(sys.stdin)\n"
    'print(json.dumps({"model": "claude-haiku-5-5", "max_tokens": 200, "system": "Write a friendly line about the topic.",'
    ' "messages": [{"role": "user", "content": case["topic"]}]}))\n'
)
CHECK = (
    "import re\n"
    "def check(output):\n"
    "    problems = []\n"
    "    if len(output) > 60:\n"
    "        problems.append(f'{len(output)} characters; at most 60.')\n"
    "    if re.search(r'[0-9]', output):\n"
    "        problems.append('Has a digit.')\n"
    "    return problems\n"
)


@pytest.mark.live
def test_a_live_run_on_cheap_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key = dotenv_values(ROOT / ".env").get("SMOKE_GENERATION_API_KEY")
    assert key, "add SMOKE_GENERATION_API_KEY to the repo's .env"
    (tmp_path / ".env").write_text(f"GENERATION_API_KEY={key}\n")
    (tmp_path / "whetstone.toml").write_text(
        '[models]\nrewrite = { via = "claude-code", model = "claude-haiku-5-5" }\n\n[prices]\n"claude-haiku-5-5" = [0.10, 0.50]\n'
    )
    prompt = tmp_path / "prompts" / "smoke"
    (prompt / "cases").mkdir(parents=True)
    (prompt / "checks").mkdir()
    (prompt / "harness.py").write_text(HARNESS)
    (prompt / "checks" / "short.py").write_text(CHECK)
    settings = {"harness": f"{sys.executable} prompts/smoke/harness.py", "provider": "anthropic", "model": "claude-haiku-5-5"}
    toml = "".join(f"{k} = {json.dumps(v)}\n" for k, v in settings.items()) + 'editable = "Write a friendly line about the topic."\n'
    (prompt / "prompt.toml").write_text(toml)
    for i, topic in enumerate(["The year 2026 in running", "Ten tips for sleeping well", "A 5k race on Sunday", "Drinking 3 litres of water"]):
        (prompt / "cases" / f"case-{i}.json").write_text(json.dumps({"topic": topic}))
    monkeypatch.chdir(tmp_path)

    code = run(["run", "smoke", "--model", "claude-haiku-5-5", "--budget", "12", "--foreground"], make_model=production_model)

    assert code in (0, 1)  # 1: no version beat the original, said loudly; still a working run
    [folder] = (prompt / "runs").glob("run-*")
    assert (folder / "report.md").is_file()
    cost = json.loads((folder / "cost.json").read_text())
    assert cost["generation"]["calls"] > 0
    assert sum(role["dollars"] for role in cost.values()) < 0.25
