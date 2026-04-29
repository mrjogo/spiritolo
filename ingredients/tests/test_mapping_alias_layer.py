import pytest

from ingredients.mapping.alias_layer import resolve_alias
from ingredients.mapping.types import Resolved, Pending


@pytest.mark.usefixtures("fixture_taxonomy")
def test_exact_alias_hit_returns_resolved(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    result = resolve_alias(conn, "lemon juice")
    assert isinstance(result, Resolved)
    assert result.taxonomy_node_id == ids["lemon_juice"]
    assert result.source == "alias"


def test_unknown_string_returns_pending(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    result = resolve_alias(conn, "fancy unknown thing")
    assert isinstance(result, Pending)


def test_alias_with_extra_whitespace_does_not_match(fixture_taxonomy):
    # The orchestrator normalizes before calling; alias_layer expects
    # already-normalized input. Confirming the contract.
    conn, _ = fixture_taxonomy
    result = resolve_alias(conn, "  lemon juice  ")
    assert isinstance(result, Pending)
