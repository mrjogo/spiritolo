"""CLI for the one-time corpus/pages migration into the hosted homes.

  python -m corpus_loader import-pages --sqlite data/scraper.db
  python -m corpus_loader load-corpus  --sqlite data/scraper.db --html-dir data/html

``import-pages`` moves the SQLite ``pages`` work-queue into Postgres ``pages``;
``load-corpus`` uploads each fetched page's HTML to the object store and sets
``pages.r2_key``. Postgres comes from ``SUPABASE_DB_URL``; object storage from
the ``S3_*`` env vars (see docs/migration.md). Run ``import-pages`` before
``load-corpus``.
"""
from __future__ import annotations

import argparse
import os
import sqlite3

import psycopg
from dotenv import load_dotenv

from .import_pages import import_pages
from .load import default_client
from .upload import load_corpus


def _connect_pg() -> psycopg.Connection:
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise SystemExit("SUPABASE_DB_URL is not set")
    return psycopg.connect(url, autocommit=True)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="corpus_loader", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_import = sub.add_parser("import-pages", help="SQLite pages -> Postgres pages.")
    p_import.add_argument("--sqlite", default="data/scraper.db")

    p_load = sub.add_parser("load-corpus", help="Local HTML -> R2; set pages.r2_key.")
    p_load.add_argument("--sqlite", default="data/scraper.db")
    p_load.add_argument("--html-dir", default="data/html")
    p_load.add_argument("--bucket", default=os.environ.get("S3_BUCKET"))

    args = parser.parse_args(argv)
    sqlite_conn = sqlite3.connect(args.sqlite)
    try:
        with _connect_pg() as pg:
            if args.cmd == "import-pages":
                stats = import_pages(sqlite_conn, pg)
            else:
                stats = load_corpus(
                    sqlite_conn, pg, default_client(), args.bucket, args.html_dir
                )
    finally:
        sqlite_conn.close()
    print(" ".join(f"{k}={v}" for k, v in stats.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
