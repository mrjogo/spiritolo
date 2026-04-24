"""CLI helpers shared across pipeline scripts.

Kept tiny on purpose: one helper per pain point, uniform behavior everywhere.
"""

from __future__ import annotations

import sys
from typing import TextIO


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
