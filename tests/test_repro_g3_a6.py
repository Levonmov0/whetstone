from whetstone.entry.cli import _calls


def test_one_judge_call_is_singular() -> None:
    assert _calls(1, 1) == "1 generation call and 1 judge call"
    assert _calls(2, 4) == "2 generation calls and 4 judge calls"
