import json

import pytest

from ingredients.dedup.prompt import (
    SYSTEM_PROMPT, build_user_prompt, parse_response, prompt_hash,
)


def test_build_user_prompt_includes_raw_and_candidates():
    prompt = build_user_prompt(
        raw_name="Best Old Fashioned Recipe",
        normalized="best old fashioned recipe",
        candidates=[
            {"canonical_name": "old fashioned", "similarity": 0.62},
            {"canonical_name": "manhattan",     "similarity": 0.31},
        ],
    )
    assert "Best Old Fashioned Recipe" in prompt
    assert "old fashioned" in prompt
    assert "manhattan" in prompt


def test_parse_response_chose():
    raw = json.dumps({"action": "chose", "canonical_name": "old fashioned"})
    obj = parse_response(raw)
    assert obj == {"action": "chose", "canonical_name": "old fashioned"}


def test_parse_response_propose():
    raw = json.dumps({"action": "propose", "canonical_name": "smoked old fashioned"})
    obj = parse_response(raw)
    assert obj == {"action": "propose", "canonical_name": "smoked old fashioned"}


def test_parse_response_abstain():
    raw = json.dumps({"action": "abstain"})
    obj = parse_response(raw)
    assert obj == {"action": "abstain"}


def test_parse_response_strips_code_fence():
    raw = "```json\n" + json.dumps({"action": "chose", "canonical_name": "negroni"}) + "\n```"
    obj = parse_response(raw)
    assert obj["action"] == "chose"


def test_parse_response_rejects_unknown_action():
    with pytest.raises(ValueError):
        parse_response(json.dumps({"action": "merge", "canonical_name": "x"}))


def test_parse_response_chose_requires_canonical_name():
    with pytest.raises(ValueError):
        parse_response(json.dumps({"action": "chose"}))


def test_prompt_hash_stable_across_candidate_ordering():
    h1 = prompt_hash(
        "Best Old Fashioned Recipe", "best old fashioned recipe",
        [{"canonical_name": "old fashioned", "similarity": 0.62},
         {"canonical_name": "manhattan",     "similarity": 0.31}],
    )
    h2 = prompt_hash(
        "Best Old Fashioned Recipe", "best old fashioned recipe",
        [{"canonical_name": "manhattan",     "similarity": 0.31},
         {"canonical_name": "old fashioned", "similarity": 0.62}],
    )
    assert h1 == h2
