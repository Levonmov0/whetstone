import json
from pathlib import Path

import httpx2 as httpx
import pytest

from tests.test_claude_code import REPLY, fake_claude
from tests.test_run_cli import make_run_suite, writer
from whetstone.entry.cli import production_rewrite, run

REWRITE = {"max_tokens": 8000, "messages": [{"role": "user", "content": "Improve this prompt."}]}


@pytest.mark.parametrize("settings", ["", '[models]\nrewrite = { via = "claude-code" }\n'])
def test_rewrites_go_through_claude_code_by_default(settings: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "whetstone.toml").write_text(settings)
    record = fake_claude(tmp_path, monkeypatch, REPLY)

    result = production_rewrite(tmp_path)(REWRITE)

    assert result.output == "```\nKeep it short.\n```"
    assert json.loads(record.read_text())["stdin"] == "Improve this prompt."


def test_claude_code_rewrites_can_name_a_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "whetstone.toml").write_text('[models]\nrewrite = { via = "claude-code", model = "claude-sonnet-5-5" }\n')
    record = fake_claude(tmp_path, monkeypatch, REPLY)

    production_rewrite(tmp_path)(REWRITE)

    assert json.loads(record.read_text())["argv"][-2:] == ["--model", "claude-sonnet-5-5"]


def test_api_rewrites_go_to_anthropic_with_their_own_key(tmp_path: Path) -> None:
    (tmp_path / "whetstone.toml").write_text('[models]\nrewrite = { via = "api", model = "claude-sonnet-5-5" }\n')
    (tmp_path / ".env").write_text("REWRITE_API_KEY=rewrite-key\nGENERATION_API_KEY=generation-key\n")
    sent: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={
            "id": "m", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5", "stop_reason": "end_turn", "stop_sequence": None,
            "content": [{"type": "text", "text": "```\nKeep it short.\n```"}], "usage": {"input_tokens": 12, "output_tokens": 7},
        })  # fmt: skip

    result = production_rewrite(tmp_path, transport=httpx.MockTransport(handle))(REWRITE)

    assert result.output == "```\nKeep it short.\n```"
    [request] = sent
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    # SDK 2.x sends a passed api_key as a bearer token; what matters is that it is the rewrite key.
    assert [c for c in (request.headers.get("x-api-key"), request.headers.get("authorization")) if c] in (["rewrite-key"], ["Bearer rewrite-key"])
    assert json.loads(request.content) == {**REWRITE, "model": "claude-sonnet-5-5"}


@pytest.mark.parametrize(
    ("settings", "env", "error"),
    [
        ('[models]\nrewrite = { via = "api", model = "claude-sonnet-5-5" }\n', "", "REWRITE_API_KEY is not set in"),
        ('[models]\nrewrite = { via = "api" }\n', "REWRITE_API_KEY=k\n", 'rewrite.via = "api" needs a model'),
        ('[models]\nrewrite = { via = "other" }\n', "", 'rewrite.via must be "claude-code" or "api"'),
    ],
)
def test_a_bad_rewrite_setting_stops_the_run_before_any_generation(
    settings: str, env: str, error: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_run_suite(tmp_path, settings=settings)
    (tmp_path / ".env").write_text(env)
    model = writer()
    monkeypatch.chdir(tmp_path)

    code = run(["run", "daily", "--model", "cheap-model", "--foreground"], make_model=lambda _settings: model)

    assert code == 2
    assert error in capsys.readouterr().err
    assert model.requests == []
