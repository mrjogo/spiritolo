"""Build the SQLite database from a staging pg_dump.

  cd scripts && uv run python -m pg_to_sqlite path/to/spiritolo-staging-*.dump out/spiritolo.db

Needs ``pg_restore`` on PATH (postgresql-client; any major ≥ the dump's server).
Never connects to Postgres. Exit status is 2 when the result has foreign-key
violations or the dump carried tables this ETL does not know about.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import etl


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pg_to_sqlite", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dump", type=Path, help="pg_dump custom-format archive (*.dump)")
    parser.add_argument("out", type=Path, help="SQLite file to create")
    parser.add_argument("--force", action="store_true", help="replace an existing output file")
    args = parser.parse_args(argv)
    if not args.dump.is_file():
        parser.error(f"{args.dump} is not a file")
    report = etl(args.dump, args.out, force=args.force)
    if report.fk_violations or report.unknown:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
