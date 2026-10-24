"""The pg_dump → SQLite ETL, fed plain-SQL COPY text (no Postgres needed)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from pg_to_sqlite import (
    etl,
    iter_copy_blocks,
    parse_pg_array,
    timestamp,
    unescape_field,
)

DUMP = r"""
--
-- PostgreSQL database dump
--
SET client_encoding = 'UTF8';

COPY public.taxonomy_nodes (id, slug, display_name, node_kind, created_at, is_cluster_node, default_role, is_defining_garnish, updated_at, status) FROM stdin;
1	gin	Gin	\N	2026-01-02 03:04:05.678901+00	t	\N	f	2026-01-02 03:04:05.678901+00	live
2	tanqueray	Tanqueray	brand	2026-01-03 00:00:00+00	f	\N	f	2026-01-03 00:00:00+00	live
\.

COPY public.taxonomy_edges (parent_id, child_id, created_at, updated_at) FROM stdin;
1	2	2026-01-03 00:00:00+00	2026-01-03 00:00:00+00
\.

COPY public.recipes (id, source_url, site, source, title, author, image_url, equipment, canonical_name, cluster_id, variant_key, recipe_slug, created_at, updated_at) FROM stdin;
10	https://example.test/martini	example	{"@type": "Recipe", "name": "Martini\\ttwist"}	Martini	\N	\N	{shaker,"mixing glass"}	martini	\N	\N	\N	2026-02-01 12:00:00-05	2026-02-01 12:00:00-05
\.

COPY public.recipe_ingredients (id, recipe_id, position, name, amount, amount_max, unit, modifiers, raw_text) FROM stdin;
100	10	0	gin	2.5	\N	oz	{}	2 1/2 oz gin
101	10	1	\N	\N	\N	\N	{chilled,"very \\"dry\\""}	a mystery
\.

COPY public.jobs (id, stage, version, kind, payload, state, requires_approval, approved, approved_by, approved_at, cost_estimate_cents, cost_actual_cents, max_cost_cents, progress, error_code, worker_id, last_heartbeat, created_by, created_at, started_at, finished_at, llm_provider, llm_model, error_detail) FROM stdin;
5	map-ingredient	v4	run	{}	succeeded	t	t	6a4b5c6d-0000-0000-0000-000000000000	\N	12	9	100	{"done": 3}	\N	w1	\N	6a4b5c6d-0000-0000-0000-000000000001	2026-03-01 00:00:00+00	2026-03-01 00:00:01+00	2026-03-01 00:01:00+00	ollama	qwen3:14b	\N
6	parse-ingredients	v2	run	{}	claimed	f	f	\N	\N	\N	\N	\N	{}	\N	\N	\N	\N	2026-03-02 00:00:00+00	\N	\N	\N	\N	\N
\.

COPY public.profiles (id, is_admin, created_at, updated_at) FROM stdin;
6a4b5c6d-0000-0000-0000-000000000001	t	2026-01-01 00:00:00+00	2026-01-01 00:00:00+00
\.

COPY public.worker_status (worker_id, last_seen, providers, stages) FROM stdin;
w1	2026-03-01 00:00:00+00	{ollama}	{map-ingredient}
\.

COPY audit.log (id, ts, table_name, pk, op, actor_kind, actor_id, source, before, after, changed_keys, job_id) FROM stdin;
1	2026-02-01 17:00:00+00	recipes	10	U	worker	5	job:map-ingredient	{"title": "Old"}	{"title": "Martini"}	{title}	5
\.
"""


def test_unescape_field():
    assert unescape_field("\\N") is None
    assert unescape_field("plain") == "plain"
    assert unescape_field("a\\tb\\nc\\\\d") == "a\tb\nc\\d"
    assert unescape_field("\\101\\x41") == "AA"


def test_parse_pg_array():
    assert parse_pg_array("{}") == []
    assert parse_pg_array("{a,b}") == ["a", "b"]
    assert parse_pg_array('{shaker,"mixing glass",NULL,"a\\"q"}') == ["shaker", "mixing glass", None, 'a"q']
    assert parse_pg_array('{"NULL"}') == ["NULL"]


def test_timestamp_to_utc_iso():
    assert timestamp("2026-02-01 12:00:00-05") == "2026-02-01T17:00:00.000Z"
    assert timestamp("2026-01-02 03:04:05.678901+00") == "2026-01-02T03:04:05.678Z"


def test_iter_copy_blocks_streams_tables():
    blocks = list(iter_copy_blocks(DUMP.splitlines(keepends=True)))
    # The rows iterator of each block was never drained, so only the first
    # block's rows are safe to read; the header parse is what we check here.
    assert [b.table for b in blocks][:1] == ["public.taxonomy_nodes"]
    assert blocks[0].columns[:3] == ["id", "slug", "display_name"]


def test_etl_builds_sqlite(tmp_path: Path):
    out = tmp_path / "spiritolo.db"
    report = etl(Path("unused.dump"), out, lines=DUMP.splitlines(keepends=True))

    assert report.loaded == {
        "taxonomy_nodes": 2, "taxonomy_edges": 1, "recipes": 1,
        "recipe_ingredients": 2, "jobs": 2, "audit_log": 1,
    }
    assert report.skipped == {"public.profiles": 1, "public.worker_status": 1}
    assert report.unknown == {}
    assert report.fk_violations == []

    db = sqlite3.connect(out)
    db.row_factory = sqlite3.Row
    node = db.execute("select * from taxonomy_nodes where id = 1").fetchone()
    assert node["is_cluster_node"] == 1 and node["node_kind"] is None
    assert node["created_at"] == "2026-01-02T03:04:05.678Z"

    recipe = db.execute("select * from recipes where id = 10").fetchone()
    assert json.loads(recipe["source"]) == {"@type": "Recipe", "name": "Martini\ttwist"}
    assert json.loads(recipe["equipment"]) == ["shaker", "mixing glass"]
    assert recipe["created_at"] == "2026-02-01T17:00:00.000Z"

    ing = {r["id"]: r for r in db.execute("select * from recipe_ingredients")}
    assert ing[100]["amount"] == 2.5 and json.loads(ing[100]["modifiers"]) == []
    assert ing[101]["name"] is None and json.loads(ing[101]["modifiers"]) == ["chilled", 'very "dry"']

    jobs = {r["id"]: r for r in db.execute("select * from jobs")}
    assert jobs[5]["state"] == "done" and jobs[6]["state"] == "queued"
    assert jobs[5]["created_by"] == "6a4b5c6d-0000-0000-0000-000000000001"
    assert "requires_approval" not in jobs[5].keys()

    audit = db.execute("select * from audit_log").fetchone()
    assert audit["op"] == "U" and json.loads(audit["changed_keys"]) == ["title"]
    assert audit["ts"] == "2026-02-01T17:00:00.000Z"

    # Schema came from the bundled migrations, so the ledger is populated and
    # a fresh application open finds nothing to apply.
    assert db.execute("select count(*) from schema_migrations").fetchone()[0] >= 1
    db.close()


def test_etl_refuses_to_overwrite(tmp_path: Path):
    out = tmp_path / "x.db"
    out.write_bytes(b"")
    with pytest.raises(SystemExit):
        etl(Path("unused.dump"), out, lines=[])
    etl(Path("unused.dump"), out, force=True, lines=[])
    assert out.stat().st_size > 0


def test_fk_violations_are_reported(tmp_path: Path):
    dump = (
        "COPY public.taxonomy_edges (parent_id, child_id, created_at, updated_at) FROM stdin;\n"
        "7\t8\t2026-01-03 00:00:00+00\t2026-01-03 00:00:00+00\n"
        "\\.\n"
    )
    report = etl(Path("unused.dump"), tmp_path / "y.db", lines=dump.splitlines(keepends=True))
    assert len(report.fk_violations) == 2  # both ends dangle
