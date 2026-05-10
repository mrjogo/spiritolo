"""End-to-end smoke tests for upload-to-staging.

Runs the real `scripts/backup-supabase.sh` against the staging mirror to
generate the .dump + .meta.json, then invokes the uploader as a subprocess
exactly as a user would.

Skips when TEST_DB_URL is unset.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
from urllib.parse import urlparse

import psycopg
import pytest

from upload_to_staging.tables import OWNED_TABLES

from .fixtures.seed import seed


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_BACKUP_SCRIPT = _REPO_ROOT / "scripts" / "backup-supabase.sh"


def _take_backup(staging_url: str, dest_dir: pathlib.Path) -> pathlib.Path:
    env = os.environ.copy()
    env["SUPABASE_STAGING_DB_URL"] = staging_url
    proc = subprocess.run(
        [str(_BACKUP_SCRIPT), "--dest", str(dest_dir)],
        env=env,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"backup-supabase.sh failed:\n{proc.stderr.decode()}"
        )
    dumps = sorted(dest_dir.glob("spiritolo-staging-*.dump"))
    assert dumps, "backup script produced no .dump file"
    return dumps[-1]


def _run_uploader(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "upload_to_staging", *args],
        capture_output=True,
        check=False,
    )


def test_smoke_happy_path(fresh_db_pair, tmp_path):
    local_url, staging_url = fresh_db_pair
    seed(local_url)
    seed(staging_url)

    dump_path = _take_backup(staging_url, tmp_path)

    # Modify a row locally — give the uploader something to push.
    with psycopg.connect(local_url, autocommit=True) as conn:
        conn.execute("update public.recipes set name = 'Old Fashioned (v2)' "
                     "where name = 'Old Fashioned'")

    proc = _run_uploader(
        "--dump", str(dump_path),
        "--local-db", local_url,
        "--staging-db", staging_url,
        "--apply", "--yes",
    )
    assert proc.returncode == 0, (
        f"uploader failed:\nstdout:\n{proc.stdout.decode()}\n"
        f"stderr:\n{proc.stderr.decode()}"
    )

    with psycopg.connect(staging_url) as conn:
        name = conn.execute(
            "select name from public.recipes where source_url = 'http://e/1'"
        ).fetchone()[0]
    assert name == "Old Fashioned (v2)"


def test_smoke_staleness_aborts(fresh_db_pair, tmp_path):
    local_url, staging_url = fresh_db_pair
    seed(local_url)
    seed(staging_url)

    dump_path = _take_backup(staging_url, tmp_path)

    # Out-of-band write to staging AFTER the backup — simulates someone
    # using the curation UI during the work session.
    with psycopg.connect(staging_url, autocommit=True) as conn:
        conn.execute("update public.recipes set name = 'Manhattan (UI edit)' "
                     "where name = 'Manhattan'")

    # Local change too, just so there'd be something to push if we didn't abort.
    with psycopg.connect(local_url, autocommit=True) as conn:
        conn.execute("update public.recipes set name = 'Negroni (local)' "
                     "where name = 'Negroni'")

    proc = _run_uploader(
        "--dump", str(dump_path),
        "--local-db", local_url,
        "--staging-db", staging_url,
        "--apply", "--yes",
    )
    assert proc.returncode != 0
    err = proc.stderr.decode()
    assert "Staging was modified" in err or "staleness" in err.lower()

    # Negroni's name on staging should be unchanged.
    with psycopg.connect(staging_url) as conn:
        name = conn.execute(
            "select name from public.recipes where source_url = 'http://e/3'"
        ).fetchone()[0]
    assert name == "Negroni"
