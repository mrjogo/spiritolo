"""Run Supabase's database linter (splinter) against the test DB.

Fails on any WARN- or ERROR-level finding whose ``cache_key`` isn't in
``fixtures/splinter_allowlist.txt``. INFO-level findings (unused
indexes, unindexed FKs, etc.) are reported but don't fail — they're
mostly noise on a freshly-reset test DB with no query history.

The vendored ``fixtures/splinter.sql`` is the upstream linter from
https://github.com/supabase/splinter, the same query the Supabase
dashboard's "Database Linter" page runs against the cloud DB.
"""
from __future__ import annotations

import pathlib

import psycopg


_FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
_SPLINTER_SQL = _FIXTURES / "splinter.sql"
_ALLOWLIST = _FIXTURES / "splinter_allowlist.txt"


def _load_allowlist() -> set[str]:
    if not _ALLOWLIST.exists():
        return set()
    keys: set[str] = set()
    for raw in _ALLOWLIST.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            keys.add(line)
    return keys


def test_splinter_no_unallowed_warn_or_error(test_db_url: str) -> None:
    raw = _SPLINTER_SQL.read_text()
    # The vendored file is two statements: `set local search_path = '';`
    # followed by the big SELECT. psycopg3 only retains the final result
    # from a multi-statement execute, so we split them and run the
    # search_path setting separately.
    set_stmt, _, select_stmt = raw.partition(";")
    allowlist = _load_allowlist()

    with psycopg.connect(test_db_url) as conn, conn.cursor() as cur:
        cur.execute(set_stmt)
        cur.execute(select_stmt)
        rows = cur.fetchall()
        cols = [d.name for d in cur.description]

    findings = [dict(zip(cols, r)) for r in rows]
    bad = [
        f
        for f in findings
        if f["level"] in ("WARN", "ERROR")
        and f["cache_key"] not in allowlist
    ]

    if bad:
        msg_lines = [
            f"{len(bad)} unallowed splinter finding(s). Either fix the "
            "underlying issue, or add the cache_key to "
            "ingredients/tests/fixtures/splinter_allowlist.txt with a "
            "`# justification` comment.",
            "",
        ]
        for f in bad:
            msg_lines.extend([
                f"  [{f['level']}] {f['name']}",
                f"    {f['detail']}",
                f"    cache_key: {f['cache_key']}",
                "",
            ])
        raise AssertionError("\n".join(msg_lines))
