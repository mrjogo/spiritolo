# Park LLM-batch failures: stop infinite resubmits

The chunked Phase-2 drain in `_drain_mapping_in_chunks`
([ingredients/src/ingredients/cli.py:501](../../../ingredients/src/ingredients/cli.py#L501))
and the parallel `_drain_dedup_in_chunks` ([same file, L682](../../../ingredients/src/ingredients/cli.py#L682))
both have a quiet bug: any name that the LLM doesn't fully resolve in a chunk
stays at `mapper_source = 'pending_llm'` (resp. `canonical_name_source =
'pending_llm'`) and is re-submitted in the next chunk — and the next, and the
next. Failure modes that trigger this are:

- `propose_form` (a normal expected outcome — the row is queued for human
  review in `taxonomy_proposals`, but the recipe row is intentionally left
  pending),
- `propose_brand` with an unknown `parent_slug` (silent return),
- JSON parse failure / empty body (model refusal, guardrails),
- transient provider errors (5xx / 429 leaking past the existing backoff),
- DB writer exceptions (caught in `ingest_batch`, logged as `writer_error`).

Because `fetch_pending_llm_names` orders by name and limits to `chunk_size`,
the same failures sit at the top of the queue every chunk. A 10%-failure
chunk leaves 200 names parked; the next chunk pulls those 200 plus 1800 new
ones; failures accumulate monotonically until they fill the entire chunk and
crowd out new work. The loop's only termination check is `if not remaining:
break`, so once the stuck pool reaches `chunk_size` it loops forever, paying
real OpenAI-Batch money each time.

This also breaks across runs: a fresh `resolve-pending` invocation
re-submits every name that failed in any prior run, indefinitely.

## Goals

- The drain loop terminates within a single run even when some names never
  clear.
- A subsequent invocation of `resolve-pending` does not re-submit names
  that already failed in a prior run.
- Operator has an explicit, low-friction way to retry parked names after
  resolving the underlying blocker (form proposal approved, taxonomy edit
  landed, transient outage cleared).
- Fix applies to both the mapping Phase-2 drain and the dedup
  normalize-names Phase-2 drain — they share a bug shape and a state
  model.

## Non-goals

- No differentiation between failure reasons (provider error vs.
  propose_form vs. parse error). The operator chose to lump them; one
  state value, one retry command.
- No automatic retry of transient errors. A 429 or 5xx that leaks past
  the existing 30-minute backoff parks the name; operator runs
  `retry-failures` after the storm clears.
- No fix for the same bug shape in `scraper/src/scraper/classify.py`
  (`run_batch`'s drain loop). It uses different storage (`pages` table,
  `content_type IS NULL` queue gating) and different failure paths;
  flagged as a follow-up.
- No refactor to extract `mapper_*` / `canonical_name_*` ingestion
  bookkeeping into a separate table. The new state value extends the
  existing column convention.
- No transactional guarantee that the parking write commits with the
  ingest write. If a run crashes between ingest commit and the next
  chunk's parking UPDATE, a small set of stuck names will be re-submitted
  exactly once on the next invocation — accepted tradeoff for
  simplicity.

## Architecture

### State model

```
recipe_ingredients.mapper_source           ∈ {alias, lexical, pending_llm,
                                              pending_llm_tried,        ← NEW
                                              llm, abstain}

recipes.canonical_name_source              ∈ {alias, lexical, pending_llm,
                                              pending_llm_tried,        ← NEW
                                              llm, abstain}
```

`pending_llm_tried` means: "Phase 2 ran on this name at this version and
did not produce a clearing action (`chose` / `abstain`). Do not re-submit
until either the version bumps or the operator explicitly retries."

### Drain loop with parking

```
┌──────────────────────────────────────────────────────────┐
│ _drain_mapping_in_chunks                                  │
│                                                           │
│   while True:                                             │
│     names = fetch_pending_llm_names(limit=chunk_size)     │
│     if not names: break       ← terminates naturally now  │
│                                                           │
│     submit_phase2_batch(names) → batch_id                 │
│     poll until completed                                  │
│     ingest_phase2_batch(batch_id)   ← writes resolutions  │
│                                       and abstains; rows  │
│                                       that don't clear    │
│                                       stay 'pending_llm'  │
│                                                           │
│     park_attempted_names(names)     ← NEW                 │
│       UPDATE recipe_ingredients                           │
│         SET mapper_source = 'pending_llm_tried'           │
│       WHERE mapper_version = current                      │
│         AND mapper_source  = 'pending_llm'                │
│         AND lower(trim(name)) = ANY(names)                │
└──────────────────────────────────────────────────────────┘
```

The names submitted in a chunk need to flow back to the drain loop for
parking. `submit_phase2_batch` currently re-queries pending names
internally and returns only a `BatchSubmitOutcome` (submission + sidecar
path) — it does not expose the names list. Two clean options:

- **(preferred)** Extend `BatchSubmitOutcome` with a `submitted_names:
  list[str]` field. `submit_phase2_batch` populates it from the same
  `names` it builds; the drain loop reads it back. One field, no extra
  I/O, no sidecar coupling.
- (alternative) Re-load the sidecar via `load_sidecar(batch_id)` and
  read `request_map.values()`. Works but requires disk I/O and an extra
  import in the drain loop.

Spec assumes the preferred option. Same change applies to dedup's
`submit_normalize_names_batch`
([dedup/normalizer_llm.py:113](../../../ingredients/src/ingredients/dedup/normalizer_llm.py#L113)).

Cleared rows (those the LLM resolved successfully) have already moved to
`mapper_source = 'llm'` or `'abstain'` inside `ingest_phase2_batch`'s
`on_result` callback, so the parking UPDATE's `mapper_source =
'pending_llm'` predicate naturally skips them. Only stuck names flip.

Cleared rows (those the LLM resolved successfully) have already moved to
`mapper_source = 'llm'` or `'abstain'` inside `ingest_phase2_batch`'s
`on_result` callback, so the parking UPDATE's `mapper_source =
'pending_llm'` predicate naturally skips them. Only stuck names flip.

### Across-run termination

`fetch_pending_llm_names` already filters on `mapper_source =
'pending_llm'`. Parked rows are at `'pending_llm_tried'`, so they don't
appear in the queue. A fresh `resolve-pending` invocation that finds the
queue drained-or-fully-parked exits immediately ("queue drained; all
chunks ingested").

### Recovery: retry-failures

New CLI subcommand under both `map` and `normalize-names`:

```
ingredients.cli map               retry-failures [--limit N] [--yes]
ingredients.cli normalize-names   retry-failures [--limit N] [--yes]
```

Implementation:

```sql
UPDATE recipe_ingredients
   SET mapper_source = 'pending_llm'
 WHERE mapper_version = <current MAPPER_VERSION>
   AND mapper_source  = 'pending_llm_tried'
 [ LIMIT N ]
```

(Postgres doesn't support `UPDATE ... LIMIT`; the `--limit` form uses a
CTE / `WHERE id IN (SELECT … LIMIT N)` shape.)

The command prints a count of un-parked rows and exits. The operator
then runs `resolve-pending` normally to re-submit them. Without `--yes`,
print the count and confirm.

### Recovery: MAPPER_VERSION bump

Already works without change. `--reset --except-version v1` deletes
all rows at the old version (including `pending_llm_tried`); Phase 1
re-runs against `recipe_ingredients` rows that have no current-version
mapping; ambiguous results land back in `pending_llm`; Phase 2 picks
them up. Same flow as today.

### Sidecar / batch-runner changes

None. The sidecar's `request_map` already contains every submitted
name; `submit_phase2_batch` returns the `BatchSubmitOutcome` whose
sidecar carries that map. The drain loop reads it back to drive the
parking UPDATE — no schema change to the sidecar.

## Data flow

```
chunk N              chunk N+1                       next run
──────              ─────────                       ────────
fetch pending  →    fetch pending (excl. tried) →   fetch pending (excl. tried)
submit                submit                          submit
ingest:                                               (or: queue empty → exit)
  ├─ chose      →  mapper_source = 'llm'
  ├─ abstain    →  mapper_source = 'abstain'
  └─ stuck       (mapper_source stays 'pending_llm')
park stuck     →  mapper_source = 'pending_llm_tried'
```

## Error handling

- **Crash between ingest commit and parking UPDATE.** Next invocation
  re-submits the unparked stuck names exactly once and parks them at
  the next chunk end. Documented behavior, not a bug.
- **Provider terminal failure** (`failed` / `expired` / `cancelled`).
  Existing behavior unchanged: the loop returns 1, the sidecar is
  marked failed, parked-names state is whatever the prior chunks left
  it at. No partial parking from a chunk whose batch never completed.
- **Writer error inside `on_result`.** Already caught and counted as
  `writer_error`. The parking UPDATE that follows still runs and
  parks any names that didn't reach a terminal state — including these.
- **Empty `pending_llm` queue at start of run.** Loop exits on the
  first iteration's `if not names: break` with no batch submitted; same
  as today.
- **Operator runs `retry-failures` while a drain is in flight.** Safe
  but undefined ordering: some retried names may end up re-parked by
  the in-flight chunk. Operators should run retries between drain
  invocations. (No lock; the cost of a stray re-park is one wasted
  chunk slot.)

## Telemetry

Drain summary gains one line, printed only when N > 0:

```
parked N names as pending_llm_tried (run 'map retry-failures' to retry)
```

`retry-failures` prints:

```
unparked N names; run 'map resolve-pending --provider …' to re-submit
```

No new metrics, no new logs inside the loop — the existing per-chunk
logs already show drained/total.

## Testing

**Mapping drain:**
- `test_drain_parks_stuck_names`: simulate a chunk whose ingest leaves
  one name at `pending_llm` (e.g., `propose_form` action). Verify the
  row is at `pending_llm_tried` after the parking step and that the
  next iteration's `fetch_pending_llm_names` returns empty (so the
  loop exits).
- `test_drain_does_not_park_cleared_names`: simulate a chunk whose
  ingest moves one name to `llm` and another to `abstain`. Verify
  neither is touched by the parking UPDATE.
- `test_retry_failures_unparks`: insert a `pending_llm_tried` row at
  the current MAPPER_VERSION, run `map retry-failures`, verify the row
  is back at `pending_llm`.
- `test_retry_failures_respects_version`: insert a `pending_llm_tried`
  row at a different MAPPER_VERSION, run `map retry-failures`, verify
  it is *not* touched.

**Dedup normalize-names drain:** parallel four tests against
`canonical_name_source` and `recipes`.

**Migration smoke test:** verify the new check constraint accepts
`pending_llm_tried` on both columns and rejects garbage.

## Files touched

- `supabase/migrations/<YYYYMMDDHHMMSS>_park_llm_tried.sql` — drop and
  recreate both check constraints with the new value.
- `ingredients/src/ingredients/mapping/types.py` — extend
  `MapperSource` literal.
- `ingredients/src/ingredients/mapping/db.py` — add
  `park_attempted_names(conn, *, mapper_version, names)` and
  `unpark_failures(conn, *, mapper_version, limit=None)`.
- `ingredients/src/ingredients/mapping/llm_resolver.py` —
  `submit_phase2_batch` now also returns the submitted names list
  (via an extended `BatchSubmitOutcome` or a new tuple return).
- `ingredients/src/ingredients/dedup/types.py` — extend
  `NormalizerSource` literal.
- `ingredients/src/ingredients/dedup/db.py` — analogous
  `park_attempted_names` / `unpark_failures` (different table /
  column).
- `ingredients/src/ingredients/dedup/normalizer_llm.py` — same
  change as `submit_phase2_batch`.
- `ingredients/src/ingredients/cli.py` —
  - call `park_attempted_names` after each chunk's ingest in both
    `_drain_mapping_in_chunks` and `_drain_dedup_in_chunks`,
  - add the parked-count log line to both summaries,
  - register `retry-failures` subparser under both `map` and
    `normalize-names`,
  - run handlers that call the unpark helpers and print the count.
- `ingredients/tests/test_mapping_resolve_pending_batch.py` — extend.
- `ingredients/tests/test_normalize_names_resolve_pending_batch.py` —
  extend.
- `ingredients/tests/test_mapping_retry_failures.py` — new.
- `ingredients/tests/test_normalize_names_retry_failures.py` — new.
- `CLAUDE.md` — note the new states and `retry-failures` commands in
  the Mapper and Recipe Dedup sections.

## Open questions

None. The crash-window tradeoff (no transactional parking) was
explicitly accepted as option B during brainstorming.
