"""Re-apply resolved overrides after a stage run, and supersede stale proposals.

The pin is a re-apply, not a lock: the durable truth is the `human_reviews` row
(the stage_fn never touches it); after each run we re-stamp the human value onto
the live output table via `apply_review()`. So a version bump recomputes freely
and the fix always wins the live row.
"""

from __future__ import annotations

from typing import Iterable

from ingredients.reviews import model


def reapply_overrides(conn, *, stage: str, ids: Iterable[str]) -> int:
    """Re-apply every resolved override for `stage` owned by `ids`.

    `ids` are recipe-id-strings (recipe stages) or names (map). Returns the count
    re-applied. `apply_review` is idempotent, so re-stamping the same value is a
    no-op — safe to call after every chunk.
    """
    override_ids = model.resolved_override_ids(conn, stage=stage, ids=ids)
    for rid in override_ids:
        conn.execute("select apply_review(%s)", (rid,))
    return len(override_ids)


def supersede_stale(conn, *, stage: str, ids: Iterable[str]) -> int:
    """Dismiss open `machine_proposal`/`distance_gate` reviews for `ids`.

    Called when a newer run has resolved those entities, so the machine's old
    proposal is moot. Never touches `human_flag`s or already-resolved overrides.
    Returns the count dismissed.
    """
    id_list = list(ids)
    if not id_list:
        return 0
    cur = conn.execute(
        "update human_reviews "
        "set state = 'dismissed', reviewed_by = 'system:superseded', reviewed_at = now() "
        "where stage = %s and state = 'open' "
        "and origin in ('machine_proposal', 'distance_gate') "
        "and (entity_id = any(%s) or split_part(entity_id, ':', 1) = any(%s))",
        (stage, id_list, id_list),
    )
    return cur.rowcount
