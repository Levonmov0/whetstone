import json
from pathlib import Path

import pytest

from tests.test_baseline import by_model
from tests.test_check_cli import make_suite
from tests.test_judges_cli import add_private_case
from whetstone.entry.cli import run


def test_the_run_folder_names_no_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = make_suite(tmp_path, {"a": "Rest today."})
    add_private_case(prompt)
    (tmp_path / "whetstone.toml").write_text('repo_providers = ["anthropic"]\n')
    monkeypatch.chdir(tmp_path)

    run(["baseline", "daily", "--models", "model-b"], make_model=lambda _settings: by_model())

    [folder] = (prompt / "runs").glob("baseline-*")
    sources = json.loads((folder / "cards.json").read_text())
    deck = json.loads((tmp_path / ".whetstone" / "decks" / "daily.json").read_text())
    assert sources == {card["card_id"].rsplit(":", 1)[1]: "model-b" if card["output"].isupper() else "fake-model" for card in deck["cards"]}
    assert "private" not in (folder / "cards.json").read_text() and ":a" not in (folder / "cards.json").read_text()
