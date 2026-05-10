import time
from unittest.mock import MagicMock

from common.llm.retry import resolve_with_retry


def test_returns_parsed_dict_on_success():
    provider = MagicMock()
    provider.resolve.return_value.raw_text = '{"action": "chose"}'
    parse_fn = MagicMock(return_value={"action": "chose"})
    result = resolve_with_retry(
        provider, system_prompt="s", user_prompt="u",
        normalized_name="vodka", parse_fn=parse_fn,
    )
    assert result == {"action": "chose"}
    assert provider.resolve.call_count == 1


def test_retries_on_exception_then_succeeds(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    provider = MagicMock()
    provider.resolve.side_effect = [
        RuntimeError("first fails"),
        MagicMock(raw_text='{"action": "chose"}'),
    ]
    parse_fn = MagicMock(return_value={"action": "chose"})
    result = resolve_with_retry(
        provider, system_prompt="s", user_prompt="u",
        normalized_name="vodka", parse_fn=parse_fn, max_attempts=3,
    )
    assert result == {"action": "chose"}
    assert provider.resolve.call_count == 2


def test_returns_none_when_all_attempts_exhausted(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    provider = MagicMock()
    provider.resolve.side_effect = RuntimeError("always fails")
    parse_fn = MagicMock()
    result = resolve_with_retry(
        provider, system_prompt="s", user_prompt="u",
        normalized_name="vodka", parse_fn=parse_fn, max_attempts=2,
    )
    assert result is None
    assert provider.resolve.call_count == 2
