"""CLI entry: argparse, orchestration of all checks, dry-run vs apply."""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import os
import pathlib
import sys
from urllib.parse import urlparse

import psycopg

from .db import (
    fetch_applied_migrations,
    fetch_dirty_rows_per_table,
    fetch_max_updated_at_per_table,
)
from .dump import sha256_of_file, sha256_of_schema_only
from .sidecar import Sidecar, SidecarError, load_sidecar
from .tables import OWNED_TABLES, OwnedTable
from .upsert import build_upsert_sql, resync_sequence_sql


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="upload-to-staging",
        description="Push dirty rows from a local Supabase to staging "
                    "behind mandatory protections.",
    )
    p.add_argument("--dump", required=True, type=pathlib.Path,
                   help="Path to the .dump file. Sidecar must exist as "
                        "<dump>.meta.json next to it.")
    p.add_argument("--local-db", default=os.environ.get("SUPABASE_DB_URL"),
                   help="Local Postgres URL (default: $SUPABASE_DB_URL).")
    p.add_argument("--staging-db",
                   default=os.environ.get("SUPABASE_STAGING_DB_URL"),
                   help="Staging Postgres URL (default: $SUPABASE_STAGING_DB_URL).")
    p.add_argument("--apply", action="store_true",
                   help="Actually push. Without it, dry-run only.")
    p.add_argument("--yes", action="store_true",
                   help="Skip the y/N confirmation before --apply.")
    return p.parse_args(argv)


def _staging_fingerprint_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    db = (parsed.path or "").lstrip("/")
    return hashlib.sha256(f"{host}:{db}".encode()).hexdigest()


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    if not args.local_db:
        return _fail("--local-db not given and SUPABASE_DB_URL unset")
    if not args.staging_db:
        return _fail("--staging-db not given and SUPABASE_STAGING_DB_URL unset")

    sidecar_path = pathlib.Path(str(args.dump) + ".meta.json")
    try:
        sidecar = load_sidecar(sidecar_path)
    except SidecarError as e:
        return _fail(str(e))

    # 2. Dump integrity
    actual_sha = sha256_of_file(args.dump)
    if actual_sha != sidecar.dump_sha256:
        return _fail(
            f"Dump file sha256 differs from sidecar:\n"
            f"  expected {sidecar.dump_sha256}\n"
            f"  actual   {actual_sha}"
        )
    actual_schema_sha = sha256_of_schema_only(args.dump)
    if actual_schema_sha != sidecar.dump_schema_sha256:
        return _fail(
            f"Dump schema-only sha256 differs from sidecar:\n"
            f"  expected {sidecar.dump_schema_sha256}\n"
            f"  actual   {actual_schema_sha}"
        )

    # 3. Staging fingerprint
    actual_fp = _staging_fingerprint_from_url(args.staging_db)
    if actual_fp != sidecar.staging_fingerprint:
        return _fail(
            f"Sidecar's staging fingerprint doesn't match --staging-db.\n"
            f"  sidecar host:db hash {sidecar.staging_fingerprint}\n"
            f"  --staging-db   hash  {actual_fp}\n"
            f"Confirm you're pointing at the right Supabase project."
        )

    # Connect to both DBs.
    with psycopg.connect(args.staging_db) as staging, \
         psycopg.connect(args.local_db) as local:

        # 4. Schema check (migration list equality)
        sidecar_migs = list(sidecar.applied_migrations)
        staging_migs = list(fetch_applied_migrations(staging))
        local_migs = list(fetch_applied_migrations(local))
        if sidecar_migs != staging_migs or sidecar_migs != local_migs:
            return _fail(_format_migration_mismatch(
                sidecar_migs, staging_migs, local_migs
            ))

        # 5. Staleness check
        T = dt.datetime.fromisoformat(sidecar.taken_at.replace("Z", "+00:00"))
        staging_max = fetch_max_updated_at_per_table(staging, OWNED_TABLES)
        stale = {
            name: ts for name, ts in staging_max.items()
            if ts is not None and ts > T
        }
        if stale:
            lines = "\n".join(
                f"  {name}: max(updated_at)={ts.isoformat()} > T={T.isoformat()}"
                for name, ts in stale.items()
            )
            return _fail(
                "Staging was modified after the dump was taken. "
                "Manual reconciliation required (re-take backup, redo work):\n"
                + lines
            )

        # 6. Compute dirty set
        dirty = fetch_dirty_rows_per_table(local, OWNED_TABLES, T)

        # 7. Print plan
        _print_plan(args, sidecar, T, dirty)

        if not args.apply:
            return 0

        # Confirm
        if not args.yes:
            ans = input("Apply to staging? [y/N] ").strip().lower()
            if ans not in ("y", "yes"):
                print("Aborted.")
                return 0

        # 8. Apply (serializable txn)
        return _apply(staging, sidecar, T, dirty)


def _format_migration_mismatch(
    sidecar_migs: list[str],
    staging_migs: list[str],
    local_migs: list[str],
) -> str:
    s_set, st_set, l_set = map(set, (sidecar_migs, staging_migs, local_migs))
    parts = ["Migration list mismatch — refuse to upload."]
    if st_set - s_set:
        parts.append(f"  staging has migrations the dump doesn't: "
                     f"{sorted(st_set - s_set)}")
    if s_set - st_set:
        parts.append(f"  dump has migrations staging doesn't: "
                     f"{sorted(s_set - st_set)}")
    if l_set - s_set:
        parts.append(f"  local has migrations the dump doesn't: "
                     f"{sorted(l_set - s_set)}")
    if s_set - l_set:
        parts.append(f"  dump has migrations local doesn't: "
                     f"{sorted(s_set - l_set)}")
    return "\n".join(parts)


def _print_plan(
    args: argparse.Namespace,
    sidecar: Sidecar,
    T: dt.datetime,
    dirty: dict[str, list[dict]],
) -> None:
    print(f"Dump:       {args.dump}")
    print(f"Sidecar:    {args.dump}.meta.json")
    print(f"T (taken):  {T.isoformat()}")
    print(f"Local DB:   {urlparse(args.local_db).hostname}/"
          f"{urlparse(args.local_db).path.lstrip('/')}")
    print(f"Staging DB: {urlparse(args.staging_db).hostname}/"
          f"{urlparse(args.staging_db).path.lstrip('/')}")
    print()
    print("All checks passed.")
    print()
    total = 0
    print("Dirty rows (local with updated_at > T):")
    for t in OWNED_TABLES:
        n = len(dirty.get(t.name, []))
        total += n
        print(f"  {t.name:24s} {n:>7d}")
    print(f"  {'─' * 32}")
    print(f"  {'total':24s} {total:>7d}")
    print()
    if args.apply:
        print("Applying (--apply set)...")
    else:
        print("Dry run. Re-run with --apply to push.")


def _apply(
    staging: psycopg.Connection,
    sidecar: Sidecar,
    T: dt.datetime,
    dirty: dict[str, list[dict]],
) -> int:
    staging.autocommit = False
    try:
        with staging.cursor() as cur:
            cur.execute("set transaction isolation level serializable")
            cur.execute("set constraints all deferred")

            # Re-verify staleness inside the txn — closes the gap between
            # the earlier read and the COMMIT.
            staging_max = fetch_max_updated_at_per_table(staging, OWNED_TABLES)
            stale = {
                n: ts for n, ts in staging_max.items()
                if ts is not None and ts > T
            }
            if stale:
                staging.rollback()
                return _fail(
                    "Staging changed between the pre-check and the apply txn. "
                    f"Aborted. Tables: {list(stale)}"
                )

            applied: dict[str, int] = {}
            for table in OWNED_TABLES:
                rows = dirty.get(table.name, [])
                if not rows:
                    applied[table.name] = 0
                    continue
                cols = list(rows[0].keys())
                stmt = build_upsert_sql(table, cols)
                # Batch in chunks of 1000.
                for i in range(0, len(rows), 1000):
                    batch = rows[i:i + 1000]
                    cur.executemany(
                        stmt,
                        [tuple(r[c] for c in cols) for r in batch],
                    )
                applied[table.name] = len(rows)

            for table in OWNED_TABLES:
                stmt = resync_sequence_sql(table)
                if stmt is not None:
                    cur.execute(stmt)

            staging.commit()
    except psycopg.errors.SerializationFailure as e:
        staging.rollback()
        return _fail(
            f"Serialization conflict at COMMIT — concurrent staging "
            f"write tripped SERIALIZABLE. Re-run --apply, or re-take "
            f"backup if it persists. ({e})"
        )

    print()
    print("Applied to staging:")
    total = 0
    for table in OWNED_TABLES:
        n = applied[table.name]
        total += n
        print(f"  {table.name:24s} {n:>7d}")
    print(f"  {'─' * 32}")
    print(f"  {'total':24s} {total:>7d}")
    print()
    print("Done.")
    return 0
