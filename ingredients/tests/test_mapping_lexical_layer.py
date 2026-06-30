import pytest

from ingredients.mapping.lexical_layer import (
    LEXICAL_MIN_SIM, LEXICAL_RATIO, bulk_lexical_candidates,
    lexical_candidates, resolve_lexical,
)
from ingredients.mapping.types import Pending, Resolved


def test_resolves_high_confidence_typo(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    # "lemon juicee" is a typo; trigram similarity to "lemon juice" is
    # very high, the next-best match much lower.
    result = resolve_lexical(conn, "lemon juicee")
    assert isinstance(result, Resolved)
    assert result.taxonomy_node_id == ids["lemon-juice"]
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


def test_bulk_lexical_candidates_matches_per_name(fixture_taxonomy):
    """bulk_lexical_candidates is the batch-mode optimization: results for
    each name must match what per-name lexical_candidates would return."""
    conn, _ = fixture_taxonomy
    names = ["tanqueray", "lemon juicee", "totally unrelated phrase"]
    bulk = bulk_lexical_candidates(conn, names, limit=5)

    assert set(bulk.keys()) == set(names)
    for n in names:
        per_name = lexical_candidates(conn, n, limit=5)
        # Same set of node_ids and same scores (order-equivalent).
        assert {(c["node_id"], round(c["similarity"], 6)) for c in bulk[n]} == \
               {(c["node_id"], round(c["similarity"], 6)) for c in per_name}
        # And bulk preserves descending similarity order.
        sims = [c["similarity"] for c in bulk[n]]
        assert sims == sorted(sims, reverse=True)


def test_bulk_lexical_candidates_handles_empty_input(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    assert bulk_lexical_candidates(conn, []) == {}
    assert bulk_lexical_candidates(conn, ["", ""]) == {}


def test_thresholds_are_tunable_constants():
    # Empirically tuned. See lexical_layer.py for rationale.
    assert LEXICAL_MIN_SIM == 0.75
    assert LEXICAL_RATIO == 1.5
