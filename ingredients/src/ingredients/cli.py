"""Pipeline CLI: run one stage, or the whole cold build, over the queue.

Each subcommand is one stage (`extract`, `parse`, `map`, `convert`, `cluster`,
`export`) run deterministically over its whole `stage_runs` work queue; `cold-build`
runs them all in order (extract -> parse -> map -> convert -> cluster -> export).
Every stage is idempotent, so a re-run only processes what a prior run left
undone. Writes go to whatever `SUPABASE_DB_URL` points at.
"""

from __future__ import annotations

import argparse
import os

import psycopg
from dotenv import load_dotenv

import ingredients.pipeline.stages  # noqa: F401 -- registers stage_fns into STAGE_FNS
from ingredients.pipeline.coldbuild import run_cold_build
from ingredients.pipeline.stages import STAGE_ORDER
from ingredients.worker.dispatch import STAGE_FNS


def _connect() -> psycopg.Connection:
    load_dotenv()
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise SystemExit("SUPABASE_DB_URL is not set")
    return psycopg.connect(url, autocommit=True)


def _job(args: argparse.Namespace) -> dict:
    return {"id": None, "payload": {"site": args.site, "limit": args.limit}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Spiritolo content pipeline.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for stage in [*STAGE_ORDER, "cold-build"]:
        p = sub.add_parser(stage, help=f"Run the {stage} stage over its queue.")
        p.add_argument("--site", default=None, help="Scope to one site.")
        p.add_argument("--limit", type=int, default=None, help="Process at most N entities.")
    return parser


def run(args: argparse.Namespace, conn: psycopg.Connection) -> dict:
    """Run the selected command against an open connection. Returns per-stage counts."""
    if args.cmd == "cold-build":
        return run_cold_build(conn, site=args.site, limit=args.limit)
    return {args.cmd: STAGE_FNS[args.cmd](_job(args), conn, None)}


def main() -> int:
    args = build_parser().parse_args()
    with _connect() as conn:
        results = run(args, conn)
    for stage, counts in results.items():
        print(f"{stage}: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
