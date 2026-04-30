from ingredients.dedup.alias_layer import resolve_alias
from ingredients.dedup.types import Pending, Resolved


def test_exact_alias_hit_returns_resolved(dedup_fixture):
    conn, _ = dedup_fixture
    result = resolve_alias(conn, "negroni")
    assert isinstance(result, Resolved)
    assert result.canonical_name == "negroni"
    assert result.source == "alias"


def test_typo_seed_resolves(dedup_fixture):
    conn, _ = dedup_fixture
    # 'daquiri' is seeded as an alias of 'daiquiri'
    result = resolve_alias(conn, "daquiri")
    assert isinstance(result, Resolved)
    assert result.canonical_name == "daiquiri"


def test_unknown_string_returns_pending(dedup_fixture):
    conn, _ = dedup_fixture
    result = resolve_alias(conn, "fancy unknown thing")
    assert isinstance(result, Pending)


def test_empty_string_returns_pending(dedup_fixture):
    conn, _ = dedup_fixture
    assert isinstance(resolve_alias(conn, ""), Pending)
