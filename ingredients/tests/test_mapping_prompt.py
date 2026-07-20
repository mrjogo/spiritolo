from ingredients.mapping.prompt import (
    SYSTEM_PROMPT, build_user_prompt, parse_response, prompt_hash,
)


def test_user_prompt_includes_name_unit_and_candidates():
    candidates = [
        {"slug": "lemon",       "display_name": "Lemon",       "similarity": 0.91, "parents": ["citrus"]},
        {"slug": "lemon-juice", "display_name": "Lemon Juice", "similarity": 0.88, "parents": ["lemon"]},
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
    assert '"slug": "lemon-juice"' in prompt or '"slug":"lemon-juice"' in prompt


def test_parse_response_chose_slug():
    raw = '{"action": "chose_slug", "slug": "gin"}'
    out = parse_response(raw)
    assert out == {"action": "chose_slug", "slug": "gin"}


def test_parse_response_abstain():
    assert parse_response('{"action": "abstain"}') == {"action": "abstain"}


def test_parse_response_rejects_unknown_action():
    import pytest
    with pytest.raises(ValueError):
        parse_response('{"action": "explode"}')


def test_parse_response_rejects_removed_propose_actions():
    """propose_brand / propose_form are no longer part of the contract."""
    import pytest
    with pytest.raises(ValueError):
        parse_response('{"action": "propose_brand", "slug": "x"}')
    with pytest.raises(ValueError):
        parse_response('{"action": "propose_form", "slug": "x"}')


def test_parse_response_handles_code_fence_wrapping():
    raw = '```json\n{"action": "chose_slug", "slug": "gin"}\n```'
    assert parse_response(raw) == {"action": "chose_slug", "slug": "gin"}


def test_prompt_hash_is_stable_for_identical_inputs():
    h1 = prompt_hash("lemon", "oz", "punch", [{"slug": "lemon", "display_name": "L"}])
    h2 = prompt_hash("lemon", "oz", "punch", [{"slug": "lemon", "display_name": "L"}])
    assert h1 == h2
    h3 = prompt_hash("lime", "oz", "punch", [{"slug": "lemon", "display_name": "L"}])
    assert h1 != h3
