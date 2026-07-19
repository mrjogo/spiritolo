"""Checked-in golden cases for the mapper, exercised by the eval test suite
(ingredients/tests/test_mapping_eval.py, via run_eval). Bumping MAPPER_VERSION
should be paired with re-running the eval suite until it passes.

Cases run against the fixture taxonomy in ingredients/tests/fixtures/
(NOT the production seed). Add cases when:
  - A new pattern was taught (alias added, threshold tuned).
  - A wrong mapping was caught (corrective should-abstain case).

The eval measures the *deterministic* resolution path map takes when no LLM tier
is available (the CLI cold build): alias -> lexical -> mint-provisional. A name
the alias/lexical tiers miss no longer parks as "pending_llm"; it mints a
provisional node from its deterministic kebab slug (or abstains when the name has
no slug at all). run_eval stays read-only — it computes the terminal slug via the
same ``slugify`` the mint uses, without writing nodes — so it can't leak fixture
state into sibling tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from ingredients.recipegf.slug import is_valid_slug, slugify

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
    expect_source: str | None       # 'alias' | 'lexical' | 'mint' | 'abstain'


# Fixture-anchored cases. Add new ones liberally.
EVAL_CASES: list[MapperEvalCase] = [
    # alias hits
    MapperEvalCase("gin",            "oz", "punch", "gin",          "alias"),
    MapperEvalCase("Lemon Juice",    "oz", "punch", "lemon-juice",  "alias"),
    MapperEvalCase("tanqueray gin",  "oz", "punch", "tanqueray",    "alias"),
    MapperEvalCase("bourbon",        "oz", "punch", "bourbon",      "alias"),
    # lexical hit (typo)
    MapperEvalCase("lemon juicee",   "oz", "punch", "lemon-juice",  "lexical"),
    # no live match -> mechanically mint a provisional node from the kebab slug
    MapperEvalCase("dry gin",        "oz", "punch", "dry-gin",       "mint"),
    MapperEvalCase("totally weird",  "oz", "punch", "totally-weird", "mint"),
    # un-slugifiable name -> abstain (no bad node minted)
    MapperEvalCase("!!!",            "oz", "punch", None,            "abstain"),
]


def run_eval(conn: psycopg.Connection) -> dict[str, Any]:
    """Run the deterministic path (alias + lexical + mint/abstain terminal) against
    each case. The LLM attach-tier isn't exercised here — that's covered by
    test_stage_map_llm_actions.py. The mint terminal is computed read-only from the
    normalized name's slug (mirroring mapping.mint), so no nodes are written."""
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
            # Deterministic terminal: mint from the normalized name, or abstain
            # when it can't produce a valid kebab slug.
            minted = slugify(normalized)
            if minted and is_valid_slug(minted):
                slug = minted
                source = "mint"
            else:
                slug = None
                source = "abstain"
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
