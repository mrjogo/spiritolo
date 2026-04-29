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


def test_cli_map_resolve_pending_aborts_without_yes_on_pipe(fixture_taxonomy, test_db_url):
    conn, _ = fixture_taxonomy
    # Seed one pending row.
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    rid = conn.execute(
        "insert into recipes (site, source_url, jsonld, fetched_at) "
        "values ('punch', 'https://example.com/q', '{}'::jsonb, now()) returning id"
    ).fetchone()[0]
    conn.execute(
        "insert into recipe_ingredients "
        "(recipe_id, position, raw_text, name, parse_status, parser_rule, parser_version, "
        " mapper_source, mapper_version) "
        "values (%s, 0, '1 oz unknown', 'unknown', 'parsed', 'qty_unit', 'v1', 'pending_llm', 'v1')",
        (rid,),
    )
    conn.commit()

    proc = _run_cli(
        ["map", "resolve-pending", "--provider", "claude"],
        {"SUPABASE_DB_URL": test_db_url},
    )
    # Without --yes and with non-tty stdin, the run aborts cleanly (exit 1).
    assert proc.returncode == 1
    # Nothing got resolved.
    row = conn.execute(
        "select mapper_source from recipe_ingredients where lower(trim(name))='unknown'"
    ).fetchone()
    assert row[0] == "pending_llm"


def test_cli_map_resolve_pending_empty_queue_exits_zero(fixture_taxonomy, test_db_url):
    conn, _ = fixture_taxonomy
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    conn.commit()
    proc = _run_cli(
        ["map", "resolve-pending", "--provider", "claude"],
        {"SUPABASE_DB_URL": test_db_url},
    )
    assert proc.returncode == 0


def test_review_proposals_approve_creates_node(fixture_taxonomy, test_db_url, monkeypatch):
    """Drive run_review_proposals directly with a stubbed input() so we
    don't need to wrangle a subprocess pty."""
    from ingredients.cli import run_review_proposals
    from ingredients.mapping.proposals import enqueue_form_proposal
    import argparse

    conn, ids = fixture_taxonomy
    conn.execute("truncate table taxonomy_proposals restart identity cascade")
    conn.commit()
    enqueue_form_proposal(
        conn, raw_string="lemon zest", proposed_slug="lemon_zest",
        proposed_display_name="Lemon Zest", proposed_parent_id=ids["lemon"],
        candidates=[{"node_id": ids["lemon_wheel"], "display_name": "Lemon Wheel", "similarity": 0.6}],
        mapper_version="v1",
    )

    answers = iter(["a"])  # approve first proposal
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setenv("SUPABASE_DB_URL", test_db_url)

    rc = run_review_proposals(argparse.Namespace(decided_by="tester"))
    assert rc == 0

    new_node = conn.execute(
        "select id from taxonomy_nodes where slug = 'lemon_zest'"
    ).fetchone()
    assert new_node is not None
    status = conn.execute(
        "select status, decided_by from taxonomy_proposals where raw_string = 'lemon zest'"
    ).fetchone()
    assert status == ("approved", "tester")
