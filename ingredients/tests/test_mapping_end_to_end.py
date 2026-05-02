"""Phase 1 + Phase 2 happy path against the fixture taxonomy."""

from __future__ import annotations

import psycopg

from ingredients.mapping.llm_provider import ProviderResult
from ingredients.mapping.llm_resolver import run_phase2
from ingredients.mapping.mapper import run_phase1


class StubProvider:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.model_id = "stub-1"

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        for name, reply in self.responses.items():
            if f'"name": "{name}"' in user_prompt:
                return ProviderResult(raw_text=reply, model_id=self.model_id)
        raise AssertionError(f"no stub for: {user_prompt[:200]}")


def _seed_recipes(conn: psycopg.Connection) -> int:
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    rid = conn.execute(
        "insert into recipes (site, source_url, jsonld, fetched_at) "
        "values ('punch', 'https://example.com/end', '{}'::jsonb, now()) returning id"
    ).fetchone()[0]
    rows = [
        (rid, 0, "2 oz gin",                  "gin"),
        (rid, 1, "1 oz lemon juicee",         "lemon juicee"),       # lexical
        (rid, 2, "0.5 oz bombay sapphire",    "bombay sapphire"),    # phase 2 brand auto-create
        (rid, 3, "1 dash lemon zest",         "lemon zest"),         # phase 2 form proposal
        (rid, 4, "1 oz mystery spirit",       "mystery spirit"),     # phase 2 abstain
    ]
    for _, pos, raw, name in rows:
        conn.execute(
            "insert into recipe_ingredients "
            "(recipe_id, position, raw_text, name, parse_status, parser_rule, parser_version) "
            "values (%s,%s,%s,%s,'parsed','qty_unit','v1')",
            (rid, pos, raw, name),
        )
    conn.commit()
    return rid


def test_full_pipeline_against_fixture(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    _seed_recipes(conn)

    p1 = run_phase1(conn)
    assert p1["alias"] == 1            # gin
    assert p1["lexical"] == 1          # lemon juicee
    assert p1["pending_llm"] == 3      # bombay sapphire, lemon zest, mystery spirit

    provider = StubProvider({
        "bombay sapphire": (
            '{"action": "propose_brand", "slug": "bombay_sapphire", '
            '"display_name": "Bombay Sapphire", "parent_slug": "london_dry_gin", '
            '"node_kind": "brand"}'
        ),
        "lemon zest": (
            '{"action": "propose_form", "slug": "lemon_zest", '
            '"display_name": "Lemon Zest", "parent_slug": "lemon"}'
        ),
        "mystery spirit": '{"action": "abstain"}',
    })
    p2 = run_phase2(conn, provider=provider)
    assert p2 == {"propose_brand": 1, "propose_form": 1, "abstain": 1}

    final = conn.execute(
        "select lower(trim(name)), mapper_source, taxonomy_node_id is null "
        "from recipe_ingredients order by position"
    ).fetchall()
    assert final == [
        ("gin",             "alias",       False),
        ("lemon juicee",    "lexical",     False),
        ("bombay sapphire", "llm",         False),
        ("lemon zest",      "pending_llm", True),     # awaiting human review
        ("mystery spirit",  "abstain",     True),
    ]

    # Auto-created brand exists with provenance.
    new_node = conn.execute(
        "select id from taxonomy_nodes where slug = 'bombay_sapphire'"
    ).fetchone()
    assert new_node is not None
    prov = conn.execute(
        "select source from taxonomy_provenance where node_id = %s", (new_node[0],),
    ).fetchone()
    assert prov == ("llm-mapper",)

    # Form proposal queued.
    proposals = conn.execute(
        "select raw_string, status from taxonomy_proposals"
    ).fetchall()
    assert proposals == [("lemon zest", "pending")]
