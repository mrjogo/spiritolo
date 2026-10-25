"""The packed request/response envelope the provider chain speaks."""
from __future__ import annotations

import json

from common.providers import packing
from common.providers.packing import Item


def test_dict_payload_is_encoded_as_json_not_repr():
    raw = packing.encode_request([Item("7", {"name": "lime juice", "n": 1})])
    doc = json.loads(raw)
    assert doc == {"items": [{"id": "7", "input": {"name": "lime juice", "n": 1}}]}
    assert "'name'" not in raw


def test_string_payload_round_trips():
    raw = packing.encode_request([Item("a", "fancy amaro"), Item("b", None)])
    assert json.loads(raw)["items"] == [
        {"id": "a", "input": "fancy amaro"},
        {"id": "b", "input": None},
    ]
    assert packing.decode_request(raw) == ["a", "b"]


def test_envelope_instructions_name_the_wire_format():
    text = packing.ENVELOPE_INSTRUCTIONS
    for word in ('"results"', '"id"', '"answer"', '"items"', '"input"'):
        assert word in text
    # DeepSeek's JSON mode rejects a prompt that never says "json".
    assert "json" in text


def test_envelope_schema_wraps_answer_schema_strictly():
    answer = {"type": "object", "properties": {"x": {"type": "string"}},
              "required": ["x"], "additionalProperties": False}
    schema = packing.envelope_schema(answer)
    assert schema["required"] == ["results"]
    assert schema["additionalProperties"] is False
    row = schema["properties"]["results"]["items"]
    assert row["required"] == ["id", "answer"]
    assert row["additionalProperties"] is False
    assert row["properties"]["answer"] == answer


def test_decode_response_reads_envelope():
    raw = packing.encode_response([{"id": "1", "answer": {"a": 1}}, {"id": "2", "error": "x"}])
    assert packing.decode_response(raw) == {"1": {"a": 1}}


def test_decode_response_tolerates_bare_list_and_fence():
    assert packing.decode_response('[{"id": "1", "answer": "gin"}]') == {"1": "gin"}
    fenced = '```json\n{"results": [{"id": "1", "answer": "gin"}]}\n```'
    assert packing.decode_response(fenced) == {"1": "gin"}


def test_decode_response_stringifies_numeric_ids():
    assert packing.decode_response('{"results": [{"id": 5, "answer": 1}]}') == {"5": 1}


def test_decode_response_unreadable_text_parks_everything():
    assert packing.decode_response('{"action": "merge"}') == {}
    assert packing.decode_response('{"results": [{"id": "1", "ans') == {}
    assert packing.decode_response("") == {}
