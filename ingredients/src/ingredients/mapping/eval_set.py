"""Checked-in golden cases for the mapper. Bumping MAPPER_VERSION should
be paired with re-running --review until it passes.

Cases run against the fixture taxonomy in ingredients/tests/fixtures/
(NOT the production seed). Add cases when:
  - A new pattern was taught (alias added, threshold tuned).
  - A wrong mapping was caught (corrective should-abstain case).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from .alias_layer import resolve_alias
from .lexical_layer import resolve_lexical
from .normalize import normalize_name
from .types import Pending, Resolved


@dataclass
class MapperEvalCase:
    raw_name: str
    parser_unit: str | None
    site: str | None
    expect_node_slug: str | None
    expect_source: str | None       # 'alias' | 'lexical' | 'pending_llm' | 'llm' | 'abstain'


# Fixture-anchored cases. Add new ones liberally.
EVAL_CASES: list[MapperEvalCase] = [
    # alias hits
    MapperEvalCase("gin",            "oz", "punch", "gin",          "alias"),
    MapperEvalCase("Lemon Juice",    "oz", "punch", "lemon-juice",  "alias"),
    MapperEvalCase("tanqueray gin",  "oz", "punch", "tanqueray",    "alias"),
    MapperEvalCase("bourbon",        "oz", "punch", "bourbon",      "alias"),
    # lexical hit (typo)
    MapperEvalCase("lemon juicee",   "oz", "punch", "lemon-juice",  "lexical"),
    # ambiguous lexical -> pending_llm
    MapperEvalCase("dry gin",        "oz", "punch", None,           "pending_llm"),
    # off-corpus -> pending_llm (Phase 1 only)
    MapperEvalCase("totally weird",  "oz", "punch", None,           "pending_llm"),
]


def run_eval(conn: psycopg.Connection) -> dict[str, Any]:
    """Run Phase 1 (alias + lexical) against each case. Phase 2 isn't
    exercised here — that's covered by test_mapping_llm_resolver.py."""
    cases: list[dict[str, Any]] = []
    passed = 0
    failed = 0
    for case in EVAL_CASES:
        normalized = normalize_name(case.raw_name)
        result = resolve_alias(conn, normalized)
        if isinstance(result, Pending):
            result = resolve_lexical(conn, normalized)
        slug = None
        source: str
        if isinstance(result, Resolved):
            slug_row = conn.execute(
                "select slug from taxonomy_nodes where id = %s", (result.taxonomy_node_id,),
            ).fetchone()
            slug = slug_row[0] if slug_row else None
            source = result.source
        else:
            source = "pending_llm"
        ok = (
            (case.expect_node_slug is None or slug == case.expect_node_slug)
            and (case.expect_source is None or source == case.expect_source)
        )
        cases.append({
            "raw": case.raw_name, "ok": ok, "slug": slug, "source": source,
        })
        if ok:
            passed += 1
        else:
            failed += 1
    return {"passed": passed, "failed": failed, "cases": cases}
