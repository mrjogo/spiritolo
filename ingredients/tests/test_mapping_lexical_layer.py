import pytest

from ingredients.mapping.lexical_layer import (
    LEXICAL_MIN_SIM, LEXICAL_RATIO, lexical_candidates, resolve_lexical,
)
from ingredients.mapping.types import Pending, Resolved


def test_resolves_high_confidence_typo(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    # "lemon juicee" is a typo; trigram similarity to "lemon juice" is
    # very high, the next-best match much lower.
    result = resolve_lexical(conn, "lemon juicee")
    assert isinstance(result, Resolved)
    assert result.taxonomy_node_id == ids["lemon_juice"]
    assert result.source == "lexical"


def test_pending_when_top1_too_close_to_top2(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    # "gin" matches both 'gin' and 'london dry gin' with high similarity;
    # the ratio guard should reject the ambiguous case in favor of LLM.
    # NOTE: 'gin' is also an alias hit in the fixture, but resolve_lexical
    # is called only after the alias layer misses, so we test it directly
    # with a string that has multiple lexical neighbors.
    result = resolve_lexical(conn, "dry gin")
    assert isinstance(result, Pending)


def test_pending_when_below_min_sim(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    result = resolve_lexical(conn, "totally unrelated phrase")
    assert isinstance(result, Pending)


def test_lexical_candidates_returns_top_n_with_scores(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    cands = lexical_candidates(conn, "tanqueray", limit=5)
    assert len(cands) >= 1
    assert cands[0]["display_name"] == "Tanqueray"
    assert cands[0]["similarity"] >= LEXICAL_MIN_SIM
    assert "node_id" in cands[0]


def test_thresholds_are_tunable_constants():
    # Sanity guard: values should match the spec's "fail closed" stance.
    assert LEXICAL_MIN_SIM == 0.92
    assert LEXICAL_RATIO == 1.5
