from ingredients.mapping.prompt import (
    SYSTEM_PROMPT, build_user_prompt, parse_response, prompt_hash,
)


def test_user_prompt_includes_name_unit_and_candidates():
    candidates = [
        {"node_id": 1, "display_name": "Lemon",       "similarity": 0.91, "parents": ["citrus"]},
        {"node_id": 2, "display_name": "Lemon Juice", "similarity": 0.88, "parents": ["lemon"]},
    ]
    prompt = build_user_prompt(
        normalized_name="lemon",
        parser_unit="oz",
        site="punch",
        candidates=candidates,
    )
    assert "lemon" in prompt
    assert "oz" in prompt
    assert "punch" in prompt
    assert "Lemon Juice" in prompt
    assert '"node_id": 1' in prompt or '"node_id":1' in prompt or "node_id=1" in prompt


def test_parse_response_chosen_node():
    raw = '{"action": "chose", "node_id": 17}'
    out = parse_response(raw)
    assert out == {"action": "chose", "node_id": 17}


def test_parse_response_brand_proposal():
    raw = (
        '{"action": "propose_brand", "slug": "tanqueray", '
        '"display_name": "Tanqueray", "parent_slug": "london-dry-gin", '
        '"node_kind": "brand"}'
    )
    out = parse_response(raw)
    assert out["action"] == "propose_brand"
    assert out["slug"] == "tanqueray"
    assert out["node_kind"] == "brand"


def test_parse_response_form_proposal():
    raw = (
        '{"action": "propose_form", "slug": "lemon-zest", '
        '"display_name": "Lemon Zest", "parent_slug": "lemon"}'
    )
    out = parse_response(raw)
    assert out["action"] == "propose_form"
    assert out["slug"] == "lemon-zest"


def test_parse_response_abstain():
    assert parse_response('{"action": "abstain"}') == {"action": "abstain"}


def test_parse_response_rejects_unknown_action():
    import pytest
    with pytest.raises(ValueError):
        parse_response('{"action": "explode"}')


def test_parse_response_handles_code_fence_wrapping():
    raw = '```json\n{"action": "chose", "node_id": 5}\n```'
    assert parse_response(raw) == {"action": "chose", "node_id": 5}


def test_prompt_hash_is_stable_for_identical_inputs():
    h1 = prompt_hash("lemon", "oz", "punch", [{"node_id": 1, "display_name": "L"}])
    h2 = prompt_hash("lemon", "oz", "punch", [{"node_id": 1, "display_name": "L"}])
    assert h1 == h2
    h3 = prompt_hash("lime", "oz", "punch", [{"node_id": 1, "display_name": "L"}])
    assert h1 != h3
