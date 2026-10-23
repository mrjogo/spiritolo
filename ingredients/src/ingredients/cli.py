"""Pipeline CLI: run one stage, or the whole cold build, over the queue.

Each subcommand is one stage (`extract-recipe`, `parse-ingredients`,
`map-ingredient`, `combine-nodes`, `connect-nodes`, `convert-steps`,
`cluster-recipes`, `export-recipegf`) run deterministically over its whole
`job_items` work queue; `cold-build` runs them all in order. Every stage is
idempotent, so a re-run only processes what a prior run left undone. Writes go
to the SQLite database at `SPIRITOLO_DB` (default `data/spiritolo.db`), the
same file the app serves.
"""

from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from common.db import Connection, open_database

import ingredients.pipeline.stages  # noqa: F401 -- registers stage_fns into STAGE_FNS
from ingredients.pipeline.coldbuild import run_cold_build
from ingredients.pipeline.stages import STAGE_ORDER
from ingredients.worker.dispatch import STAGE_FNS

DEFAULT_DB_PATH = "data/spiritolo.db"


def db_path() -> str:
    """The database file the CLI operates on: ``SPIRITOLO_DB`` or the default."""
    load_dotenv()
    return os.environ.get("SPIRITOLO_DB") or DEFAULT_DB_PATH


def _connect(cmd: str) -> Connection:
    return open_database(db_path(), actor=("system", None, f"cli:{cmd}"))


def _job(args: argparse.Namespace) -> dict:
    return {"id": None, "payload": {"site": args.site, "limit": args.limit}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Spiritolo content pipeline.")
    parser.add_argument("--db", default=None, help="SQLite database path (default: $SPIRITOLO_DB).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for stage in [*STAGE_ORDER, "cold-build"]:
        p = sub.add_parser(stage, help=f"Run the {stage} stage over its queue.")
        p.add_argument("--site", default=None, help="Scope to one site.")
        p.add_argument("--limit", type=int, default=None, help="Process at most N entities.")
    return parser


def run(args: argparse.Namespace, conn: Connection) -> dict:
    """Run the selected command against an open connection. Returns per-stage counts."""
    if args.cmd == "cold-build":
        return run_cold_build(conn, site=args.site, limit=args.limit)
    return {args.cmd: STAGE_FNS[args.cmd](_job(args), conn, None)}


def main() -> int:
    args = build_parser().parse_args()
    if args.db:
        os.environ["SPIRITOLO_DB"] = args.db
    with _connect(args.cmd) as conn:
        results = run(args, conn)
    for stage, counts in results.items():
        print(f"{stage}: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
