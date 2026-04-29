import io
import os
import subprocess
import sys

import psycopg
import pytest


def _run_cli(args: list[str], env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
    env = {**os.environ, **env_overrides}
    return subprocess.run(
        [sys.executable, "-m", "ingredients.cli", *args],
        env=env, capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__)),
    )


def _seed_one(conn: psycopg.Connection) -> None:
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    rid = conn.execute(
        "insert into recipes (site, source_url, jsonld, fetched_at) "
        "values ('punch', 'https://example.com/a', '{}'::jsonb, now()) returning id"
    ).fetchone()[0]
    conn.execute(
        "insert into recipe_ingredients "
        "(recipe_id, position, raw_text, name, parse_status, parser_rule, parser_version) "
        "values (%s, 0, '2 oz gin', 'gin', 'parsed', 'qty_unit', 'v1')",
        (rid,),
    )
    conn.commit()


def test_cli_map_phase1_dry_run_reports_counts(fixture_taxonomy, test_db_url):
    conn, _ = fixture_taxonomy
    _seed_one(conn)
    # Force the CLI's IngredientsDatabase to point at the test DB.
    proc = _run_cli(["map", "--dry-run"], {"SUPABASE_DB_URL": test_db_url})
    assert proc.returncode == 0, proc.stderr
    assert "Map ingredients" in proc.stdout
    assert "alias" in proc.stdout
    # Dry-run wrote nothing.
    row = conn.execute(
        "select mapper_source from recipe_ingredients where lower(trim(name))='gin'"
    ).fetchone()
    assert row[0] is None


def test_cli_map_phase1_applied_writes_alias_resolution(fixture_taxonomy, test_db_url):
    conn, ids = fixture_taxonomy
    _seed_one(conn)
    proc = _run_cli(["map"], {"SUPABASE_DB_URL": test_db_url})
    assert proc.returncode == 0, proc.stderr
    row = conn.execute(
        "select taxonomy_node_id, mapper_source, mapper_version "
        "from recipe_ingredients where lower(trim(name))='gin'"
    ).fetchone()
    assert row == (ids["gin"], "alias", "v1")
