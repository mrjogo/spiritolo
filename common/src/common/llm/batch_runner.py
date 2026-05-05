"""Flow-agnostic submit / ingest orchestration for batch providers.

Callers provide:
- A list of `rows` (anything iterable; the orchestrator just enumerates them).
- `to_request(idx, row) -> BatchRequest` — builds the prompt.
- `row_to_id(row) -> str` — the row's identity for the sidecar.request_map.
- `on_result(row_id, raw_text, error) -> None` — per-result writer; bumps
  the appropriate counter in the caller's domain.

The orchestrator handles sidecar persistence + ingest dispatch + summary
counts. Each flow (mapping, dedup, classify) keeps its own parser and
DB writer; this module knows nothing about them.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .batch_provider import BatchProvider, BatchRequest, BatchResult, BatchSubmission
from .sidecar import Sidecar, load_sidecar, mark_ingested, write_sidecar


@dataclass(frozen=True)
class BatchSubmitOutcome:
    submission: BatchSubmission
    sidecar_path: Path


def submit_batch(
    *,
    provider: BatchProvider,
    rows: list,
    to_request: Callable[[int, object], BatchRequest],
    row_to_id: Callable[[object], str],
    flow: str,
    version_constant: str,
    batches_dir: Path,
) -> BatchSubmitOutcome:
    """Build batch requests from rows, submit, persist sidecar."""
    requests = []
    request_map: dict[str, str] = {}
    for idx, row in enumerate(rows):
        req = to_request(idx, row)
        requests.append(req)
        request_map[req.custom_id] = row_to_id(row)
    submission = provider.submit(requests)
    sc = Sidecar(
        batch_id=submission.batch_id,
        provider=submission.provider,
        flow=flow,
        model_id=submission.model_id,
        version_constant=version_constant,
        submitted_at=datetime.now(timezone.utc).isoformat(),
        request_map=request_map,
    )
    path = write_sidecar(sc, batches_dir=batches_dir)
    return BatchSubmitOutcome(submission=submission, sidecar_path=path)


def ingest_batch(
    *,
    provider: BatchProvider,
    batch_id: str,
    flow: str,
    version_constant: str,
    on_result: Callable[[str, str | None, str | None], None],
    batches_dir: Path,
) -> dict[str, int]:
    """Load sidecar, fetch results, dispatch each via on_result.
    Returns a dict with {'ok': N, 'error': M}.
    """
    sc = load_sidecar(
        batch_id, batches_dir=batches_dir,
        expected_flow=flow, expected_version=version_constant,
    )
    status = provider.status(batch_id)
    if status.state != "completed":
        raise RuntimeError(
            f"batch {batch_id} not yet completed (state={status.state!r}, "
            f"{status.completed}/{status.total})"
        )
    counts: Counter[str] = Counter()
    for r in provider.fetch_results(batch_id):
        row_id = sc.request_map.get(r.custom_id)
        if row_id is None:
            counts["unmapped"] += 1
            continue
        on_result(row_id, r.raw_text, r.error)
        counts["error" if r.error or r.raw_text is None else "ok"] += 1
    sidecar_path = batches_dir / f"{batch_id}.json"
    mark_ingested(sidecar_path)
    return dict(counts)
