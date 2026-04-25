"""CLI helpers shared across pipeline scripts.

Kept tiny on purpose: one helper per pain point, uniform behavior everywhere.
"""

from __future__ import annotations

import argparse
import sys
from typing import TextIO


def add_reset_args(parser: argparse.ArgumentParser, *, stage: str) -> None:
    """Attach the standard --reset / --site-scoped reset filters to a CLI.

    Every pipeline script's --reset accepts the same trio of filters
    (--site / --except-version / --older-than), ANDed together. Without any
    filter, --reset wipes the entire scope for that stage.
    """
    parser.add_argument(
        "--reset", action="store_true",
        help=f"Delete {stage} eval rows for in-scope pages before running, "
             "forcing re-evaluation. Combine with the filters below to "
             "narrow the scope.",
    )
    parser.add_argument(
        "--except-version", metavar="V",
        help="With --reset: only delete rows whose evaluator version is NOT "
             "this value. Use to drop everything left over from a prior "
             "prompt/scorer/extractor version.",
    )
    parser.add_argument(
        "--older-than", metavar="ISO_TS",
        help="With --reset: only delete rows whose evaluated_at is before "
             "this ISO-8601 timestamp. Example: 2026-01-01T00:00:00+00:00",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip the --reset confirmation prompt. Required when stdin is "
             "not a terminal (e.g. piped/CI).",
    )


def describe_reset_scope(
    *, site: str | None, except_version: str | None, older_than: str | None,
) -> str:
    parts: list[str] = []
    parts.append(f"site={site}" if site else "all sites")
    if except_version is not None:
        parts.append(f"except-version={except_version}")
    if older_than is not None:
        parts.append(f"older-than={older_than}")
    return ", ".join(parts)


def confirm_reset(
    *,
    row_count: int,
    scope_desc: str,
    assume_yes: bool,
    stdin: TextIO | None = None,
    stdin_is_tty: bool | None = None,
    err: TextIO | None = None,
) -> bool:
    """Uniform --reset confirmation heuristic:

    - row_count == 0: nothing to reset, return True without prompting.
    - assume_yes=True (user passed --yes): log intent, return True.
    - Interactive TTY: prompt 'Reset N rows (scope)? [y/N]'. Default No.
    - Piped/redirected stdin without --yes: refuse and tell the user to pass
      --yes, so a pipeline doesn't silently consume a 'y' meant for something
      else.
    """
    err_stream = err if err is not None else sys.stderr
    in_stream = stdin if stdin is not None else sys.stdin
    is_tty = stdin_is_tty if stdin_is_tty is not None else in_stream.isatty()

    if row_count == 0:
        return True

    if assume_yes:
        err_stream.write(
            f"Resetting {row_count:,} rows ({scope_desc}); proceeding (--yes).\n"
        )
        return True

    if not is_tty:
        err_stream.write(
            f"Refusing to reset {row_count:,} rows ({scope_desc}) without --yes "
            "on non-interactive stdin.\n"
        )
        return False

    err_stream.write(
        f"About to reset {row_count:,} rows ({scope_desc}).\n"
        "Proceed? [y/N]: "
    )
    err_stream.flush()
    answer = in_stream.readline().strip().lower()
    return answer in ("y", "yes")
