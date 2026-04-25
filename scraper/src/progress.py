"""Shared progress + ETA display used by classify, extract, validate, and
any future pipeline script.

Style (classify-originated):
    \r  N,NNN/M,MMM (X.X%)  Y.Y/s  ETA 1h3m34s

Trailing spaces pad for shorter follow-up lines; the final emit ends with a
newline so subsequent stdout doesn't get stuck mid-update.
"""

from __future__ import annotations

import time
from typing import Callable, TextIO

PROGRESS_EVERY = 25
"""Row cadence between progress emits. Shared across scripts so output rate
feels consistent regardless of which pipeline is running."""


def format_eta(seconds: float) -> str:
    """Format a duration as 0s / 59s / 1m5s / 1h3m34s. Negative durations
    (the last-second rate-based ETA can briefly go sub-zero) format as 0s."""
    s = int(seconds) if seconds > 0 else 0
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m}m{s}s"
    if m:
        return f"{m}m{s}s"
    return f"{s}s"


def make_progress(
    *,
    total: int,
    out: TextIO | None = None,
    now: Callable[[], float] | None = None,
    every: int = PROGRESS_EVERY,
) -> Callable[[int], None]:
    """Return a callback `progress(done)` that emits the standard progress
    line every `every` rows and at completion (`done == total`).

    `now` lets tests inject a monotonic clock; defaults to `time.monotonic`.
    `out` lets tests capture the stream; defaults to `sys.stdout`.
    """
    import sys
    stream = out if out is not None else sys.stdout
    clock = now if now is not None else time.monotonic
    start = clock()

    def progress(done: int) -> None:
        if done != total and (every <= 0 or done % every != 0):
            return
        elapsed = clock() - start
        rate = done / elapsed if elapsed > 0 else 0.0
        remaining = max(total - done, 0)
        eta = remaining / rate if rate > 0 else 0.0
        pct = (100 * done / total) if total else 0.0
        line = (
            f"\r  {done:,}/{total:,} ({pct:.1f}%)  "
            f"{rate:.1f}/s  ETA {format_eta(eta)}    "
        )
        stream.write(line)
        stream.flush()
        if done == total:
            stream.write("\n")
            stream.flush()

    return progress
