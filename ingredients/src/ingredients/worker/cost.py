"""Cost accounting + hard cap for the worker.

A metered stage (hosted LLM, ScraperAPI) accumulates spend call-by-call. The
``CostMeter`` is the running total plus the ceiling: before a metered call is
made, ``charge`` checks whether it would push cumulative spend past the job's
``max_cost_cents`` and, if so, raises ``CostCapExceeded`` *without* recording the
spend — so the item that would have breached the cap is left unprocessed and its
cost is never counted (no double count on the aborted item).

Free / deterministic / local work costs nothing: ``charge(0)`` returns
immediately without ever consulting the cap, so a free chain is uncapped even
under a zero budget. That is the ``test_free_stage_no_cap_check`` invariant.

The meter is the *enforcement* mechanism; the durable truth of what was spent is
the sum of ``stage_runs.cost_cents`` the worker rolls up into
``jobs.cost_actual_cents`` afterwards. The two agree, but the ledger — not the
meter — is authoritative.
"""

from __future__ import annotations


class CostCapExceeded(Exception):
    """Raised when a metered call would push cumulative spend past the cap.

    Carries the numbers so the caller can log/park precisely. The offending
    charge is NOT applied — ``spent`` is the total actually incurred so far.
    """

    def __init__(self, *, attempted: int, cap: int, spent: int) -> None:
        self.attempted = attempted
        self.cap = cap
        self.spent = spent
        super().__init__(
            f"cost cap exceeded: next charge would reach {attempted}c, "
            f"cap is {cap}c (already spent {spent}c)"
        )


class CostMeter:
    """Running metered spend against an optional per-job ceiling.

    ``cap_cents=None`` means unbounded (a free job, or a metered job with no
    budget set). A non-negative cap is enforced by ``charge``. ``consultations``
    counts how many times the cap was actually inspected — free work never
    inspects it, which the free-stage test asserts.
    """

    def __init__(self, cap_cents: int | None = None) -> None:
        self.cap_cents = cap_cents
        self.spent_cents = 0
        self.consultations = 0

    def charge(self, cents: int) -> None:
        """Record ``cents`` of metered spend, or raise ``CostCapExceeded``.

        A non-positive charge is free work: it returns immediately and never
        touches the cap (so a free chain is uncapped even at a zero budget).
        """
        if cents <= 0:
            return
        self.consultations += 1
        if self.cap_cents is not None and self.spent_cents + cents > self.cap_cents:
            raise CostCapExceeded(
                attempted=self.spent_cents + cents,
                cap=self.cap_cents,
                spent=self.spent_cents,
            )
        self.spent_cents += cents
