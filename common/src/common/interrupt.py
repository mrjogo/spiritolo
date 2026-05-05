"""Two-stage SIGINT handler for long-running batch loops.

First Ctrl-C flips ``requested``; the loop is expected to drain in-flight
work (flush a write buffer, let an executor finish in-flight tasks, etc.)
and exit cleanly on its own. Second Ctrl-C restores the previous handler
and raises KeyboardInterrupt for an immediate abort — buffered work is
*not* flushed.

``request()`` lets worker code trigger the same graceful shutdown
programmatically (e.g. on a fatal API error) without raising; the result
is indistinguishable from a first Ctrl-C.

The handler installs only on the main thread (Python's signal restriction)
and only inside the ``with`` block; on exit the previous handler is restored.

Single-threaded loop with a write buffer::

    with InterruptHandler() as interrupt:
        try:
            for item in items:
                if interrupt.requested:
                    break
                buffer.append(do_work(item))
                if len(buffer) >= BATCH_FLUSH_SIZE:
                    flush(buffer)
        except KeyboardInterrupt:
            raise   # second Ctrl-C: skip flush
        flush(buffer)   # graceful exit (loop completion or first Ctrl-C)

Multi-threaded with ThreadPoolExecutor::

    with InterruptHandler() as interrupt:
        def process(row):
            if interrupt.requested:
                return
            try:
                ...
            except FatalError:
                interrupt.request()   # signal main loop to drain
                raise

        executor = ThreadPoolExecutor(max_workers=n)
        try:
            futures = [executor.submit(process, r) for r in rows]
            for f in as_completed(futures):
                if interrupt.requested:
                    break
                f.result()
        finally:
            # cancel queued futures, wait for in-flight ones to finish.
            # Second Ctrl-C interrupts this wait and exits immediately.
            executor.shutdown(wait=True, cancel_futures=True)
"""

from __future__ import annotations

import signal
import sys
from types import FrameType, TracebackType
from typing import Self


class InterruptHandler:
    def __init__(
        self,
        graceful_message: str = (
            "[interrupt received — finishing pending work; "
            "press Ctrl-C again to abort immediately]"
        ),
    ) -> None:
        self.requested = False
        self._graceful_message = graceful_message
        self._previous: object = None

    def __enter__(self) -> Self:
        self._previous = signal.signal(signal.SIGINT, self._handle)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._previous is not None:
            signal.signal(signal.SIGINT, self._previous)  # type: ignore[arg-type]

    def request(self) -> None:
        """Programmatically signal graceful shutdown — equivalent to a first
        Ctrl-C. Safe to call from worker threads. Idempotent."""
        self.requested = True

    def _handle(self, signum: int, frame: FrameType | None) -> None:
        if self.requested:
            # Restore the previous handler so a third press (or this one
            # propagated through whatever Python does next) hits the default
            # behavior. Then raise immediately.
            if self._previous is not None:
                signal.signal(signal.SIGINT, self._previous)  # type: ignore[arg-type]
            print("\n[second interrupt — aborting]", file=sys.stderr, flush=True)
            raise KeyboardInterrupt
        self.requested = True
        print(f"\n{self._graceful_message}", file=sys.stderr, flush=True)
