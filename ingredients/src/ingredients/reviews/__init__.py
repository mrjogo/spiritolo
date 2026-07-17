"""Unified stage-review layer.

One `stage_reviews` table carries every stage's flags, machine proposals, and
human overrides — a flag, a proposal, and an override are the same row
distinguished by (state, origin). Human input lives here, a table the stage_fn
never writes, so a rerun cannot clobber it ("pin survives rerun").

- `registry` — the per-stage adapter protocol + registry (the only stage-specific
  seam, alongside the SQL `apply_review` branch).
- `model` — row access over `stage_reviews`.
- `reapply` — re-apply resolved overrides after a stage run, and supersede stale
  machine proposals.
"""
