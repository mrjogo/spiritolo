from ingredients.dedup.lexical_layer import resolve_lexical, lexical_candidates
from ingredients.dedup.types import Pending, Resolved


def test_close_match_resolves(dedup_fixture):
    # 'whiskey sours' (extra s) should match 'whiskey sour' via trgm (sim=0.80).
    # Note: 'negronni' only scores 0.70 against 'negroni' — too short for the
    # LEXICAL_MIN_SIM=0.75 threshold. Longer names get more reliable trgm scores.
    conn, _ = dedup_fixture
    result = resolve_lexical(conn, "whiskey sours")
    assert isinstance(result, Resolved)
    assert result.canonical_name == "whiskey sour"
    assert result.source == "lexical"


def test_no_match_returns_pending(dedup_fixture):
    conn, _ = dedup_fixture
    result = resolve_lexical(conn, "completely unrelated phrase")
    assert isinstance(result, Pending)


def test_ambiguous_match_returns_pending(dedup_fixture):
    # If two candidates score within the ratio threshold of each other,
    # the layer abstains so Phase 2 / human can decide.
    conn, _ = dedup_fixture
    # 'martini gimlet' shares trgrams with both 'martini' and 'gimlet'.
    result = resolve_lexical(conn, "martini gimlet")
    assert isinstance(result, Pending)


def test_lexical_candidates_returns_top_n_with_scores(dedup_fixture):
    conn, _ = dedup_fixture
    cands = lexical_candidates(conn, "negronni", limit=5)
    assert len(cands) >= 1
    assert cands[0]["canonical_name"] == "negroni"
    assert "similarity" in cands[0]
    assert 0.0 <= cands[0]["similarity"] <= 1.0
