"""Stage-fn dispatch registry.

``STAGE_FNS`` maps a stage name to the callable that runs it. This module owns
the registry + the seam contract; each pipeline stage registers its own
``stage_fn`` body — the single point where a fake stage_fn is injected in
tests.

A ``stage_fn`` has the signature ``fn(job, conn, providers)`` where:
  - ``job``       is the claimed job row (a dict with ``stage`` / ``payload`` /
                  ``id`` / ``max_cost_cents`` / …),
  - ``conn``      is the worker's psycopg connection (the stage writes its
                  ``job_items`` UPSERTs through it),
  - ``providers`` is the run's ``ProviderChain`` (its chosen LLM tier, bound to
                  the job's cost meter) or ``None`` for a run that needs none.

It returns an optional mapping recorded as the job's ``progress``. Dispatch does
NOT catch stage errors — an unknown stage raises ``UnknownStage`` and any stage
exception propagates; the loop turns both into a ``failed`` job with an
``error_code`` (never a crash).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# The global registry. Stages register at import time; tests may inject a
# throwaway map into ``run`` instead of mutating this.
STAGE_FNS: dict[str, Callable[..., Any]] = {}


class UnknownStage(Exception):
    """No ``stage_fn`` is registered for a job's stage."""

    def __init__(self, stage: str) -> None:
        self.stage = stage
        super().__init__(f"no stage_fn registered for stage {stage!r}")


def register(stage: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    """Register ``fn`` as the stage_fn for ``stage`` (returns ``fn``)."""
    STAGE_FNS[stage] = fn
    return fn


def run(
    job: dict[str, Any],
    conn: Any,
    providers: Any,
    *,
    stage_fns: dict[str, Callable[..., Any]] | None = None,
) -> Any:
    """Dispatch ``job`` to its stage_fn and return the fn's result.

    ``stage_fns`` overrides the global ``STAGE_FNS`` (tests inject fakes). Raises
    ``UnknownStage`` when the job's stage has no registered fn.
    """
    registry = STAGE_FNS if stage_fns is None else stage_fns
    fn = registry.get(job["stage"])
    if fn is None:
        raise UnknownStage(job["stage"])
    return fn(job, conn, providers)
