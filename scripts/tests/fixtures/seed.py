"""Tiny shared fixture: insert identical seed data into a DB.

Three recipes, three taxonomy nodes, one cocktail alias. Kept minimal —
each owned table doesn't need data for the smoke tests to exercise the
upload pipeline; they only need to exist and be addressable.
"""
from __future__ import annotations

import psycopg


def seed(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "insert into public.recipes "
            "(source_url, site, name, jsonld, fetched_at) "
            "values "
            "('http://e/1', 'e', 'Old Fashioned', '{}'::jsonb, now()),"
            "('http://e/2', 'e', 'Manhattan',     '{}'::jsonb, now()),"
            "('http://e/3', 'e', 'Negroni',       '{}'::jsonb, now())"
        )
        # node_kind has a CHECK constraint ('brand' | 'expression'); leaving
        # it NULL is fine — it's nullable and the smoke tests don't care.
        conn.execute(
            "insert into public.taxonomy_nodes (slug, display_name) "
            "values "
            "('whiskey', 'Whiskey'),"
            "('rye',     'Rye'),"
            "('bourbon', 'Bourbon')"
        )
        conn.execute(
            "insert into public.cocktail_aliases "
            "(alias, canonical_name, source) "
            "values ('old fashioned', 'Old Fashioned', 'seed')"
        )
