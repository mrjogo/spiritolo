import json
from unittest.mock import MagicMock

import pytest

from common.llm.openai_decisions import (
    DECISIONS_PATH,
    DEFAULT_MODEL,
    DecisionsProvider,
    DecisionsRefused,
    build_decisions_request,
    choices_from_schema,
    parse_decisions_response,
)

SCHEMA = {
    "type": "object",
    "properties": {"label": {"type": "string", "enum": ["a", "b", "c"]}},
    "required": ["label"],
    "additionalProperties": False,
}


def _reply(**answer) -> str:
    return json.dumps({
        "answers": [answer],
        "model": "gpt-6-luna-2026-10-06",
        "usage": {"input_tokens": 120, "output_tokens": 0, "total_tokens": 120},
    })


def test_choices_from_schema_takes_the_single_enum_property():
    assert choices_from_schema(SCHEMA) == ("label", ["a", "b", "c"])


@pytest.mark.parametrize("schema", [
    None,
    {"type": "object", "properties": {}},
    {"type": "object", "properties": {"x": {"enum": ["1", "2"]}, "y": {"enum": ["p", "q"]}}},
    {"type": "object", "properties": {"x": {"enum": ["only"]}}},
])
def test_choices_from_schema_rejects_unusable_schemas(schema):
    with pytest.raises(ValueError):
        choices_from_schema(schema)


def test_build_request_is_one_choice_question():
    body = build_decisions_request(
        model="gpt-6-luna", instructions="sys", user_input="URL: x",
        choices=["a", "b"], question_name="label",
    )
    assert body == {
        "model": "gpt-6-luna",
        "input": "URL: x",
        "questions": [{
            "type": "choice", "name": "label", "instructions": "sys",
            "choices": [{"value": "a"}, {"value": "b"}],
        }],
    }


def test_resolve_posts_to_decisions_and_reserializes_choice_with_confidence():
    client = MagicMock()
    client.post.return_value = _reply(
        type="choice", name="label", choice="b", confidence=0.91,
        probabilities=[{"value": "a", "probability": 0.05},
                       {"value": "b", "probability": 0.91},
                       {"value": "c", "probability": 0.04}],
    )
    p = DecisionsProvider(client=client)
    out = p.resolve(system_prompt="sys", user_prompt="URL: x", response_schema=SCHEMA)

    assert out.model_id == DEFAULT_MODEL == "gpt-6-luna"
    assert json.loads(out.raw_text) == {
        "label": "b", "confidence": 0.91,
        "probabilities": {"a": 0.05, "b": 0.91, "c": 0.04},
    }
    assert p.last_usage["input_tokens"] == 120
    client.post.assert_called_once()
    args, kwargs = client.post.call_args
    assert args == (DECISIONS_PATH,)
    assert kwargs["cast_to"] is str
    assert kwargs["body"]["model"] == "gpt-6-luna"
    assert kwargs["body"]["input"] == "URL: x"
    assert kwargs["body"]["questions"][0]["instructions"] == "sys"
    assert [c["value"] for c in kwargs["body"]["questions"][0]["choices"]] == ["a", "b", "c"]


def test_confidence_falls_back_to_the_chosen_probability():
    out = parse_decisions_response(
        {"answers": [{"type": "choice", "choice": "a",
                      "probabilities": [{"value": "a", "probability": 0.7},
                                        {"value": "b", "probability": 0.3}]}]},
        question_name="label",
    )
    assert out["confidence"] == 0.7


def test_refusal_raises_decisions_refused():
    client = MagicMock()
    client.post.return_value = _reply(type="refusal", name="label")
    with pytest.raises(DecisionsRefused):
        DecisionsProvider(client=client).resolve(
            system_prompt="s", user_prompt="u", response_schema=SCHEMA)


def test_non_choice_answer_is_an_error():
    with pytest.raises(ValueError):
        parse_decisions_response(
            {"answers": [{"type": "predicate", "probability": 0.5}]}, question_name="label")


def test_resolve_without_schema_is_an_error_before_any_request():
    client = MagicMock()
    with pytest.raises(ValueError):
        DecisionsProvider(client=client).resolve(system_prompt="s", user_prompt="u")
    client.post.assert_not_called()


def test_from_env_reads_api_key(monkeypatch):
    import openai
    captured = {}
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: captured.update(kw) or object())
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    p = DecisionsProvider.from_env()
    assert captured == {"api_key": "sk-env"}
    assert p.model_id == "gpt-6-luna"


def test_from_env_requires_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        DecisionsProvider.from_env()
