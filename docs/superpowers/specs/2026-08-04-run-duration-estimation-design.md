# Run duration estimation + tracking — design

Give operators a rough, honest sense of **how long a run will take** — before they
start it (in the Start-confirm modal) and while it runs (a live "time remaining"
ticker in the run cockpit) — plus the per-item telemetry that makes those numbers
trustworthy over time. Along the way, fix the one provider-naming split that
currently makes Claude runs silently do nothing.

## Problem

Today the `/ops` console tells an operator what a run will **cost** (`_estimate_cents`),
but nothing about how **long** it will take. A run is one stage over N entities,
processed serially; duration is dominated by `(LLM calls) × (latency per call)`,
and the three things that swing latency — the fraction of items that actually hit
the LLM, output-token length, and provider load — are individually unpredictable
in advance. So a first-principles point estimate is hopeless. But those same
factors are all **baked into observed durations**: if `map-ingredient` on
`deepseek` has historically taken ~2 s/item, that number already reflects the
typical hit fraction, token lengths, and load. We record `started_at`/`finished_at`
on every `job` and `job_item` already — we just never turn that into an estimate.

Two adjacent defects surface alongside this work:

1. **Provider-name split.** The Claude provider is keyed `anthropic` on the UI +
   SQL side but `claude` on the Python worker + scraper side (both read the same
   `jobs.llm_provider`). Result: a Claude run writes `llm_provider='anthropic'`,
   the worker's `provider_id == "claude"` branch never matches, and the run
   **silently executes deterministic-only** — and is mispriced, because the SQL
   estimate keys on `anthropic` while the worker cost table keys on `claude`.
2. **No token telemetry.** Every LLM response reports its token usage; we discard
   it and keep only dollar cost, so we can't measure throughput or validate the
   cost estimate against reality.

## Non-goals

- **No statistical model.** No percentiles, confidence intervals, or variance
  modeling. The estimate is a single average snapped to a coarse bucket.
- **No load / time-of-day model.** The historical average already absorbs load;
  we do not model peak vs off-peak, day-of-week, etc. (Explicitly deferred; the
  average is the v1 load story.)
- **No changes to the provider chain's retry/timeout/cost-cap behavior.**
- **Tokens are telemetry, not an input to the estimate.** The time estimate uses
  wall-clock timing only; token capture is independent and additive.
- **No DB enum/CHECK on `llm_provider`.** Out of scope to constrain the column;
  we only standardize the value written into it.

## Design

### 1. Standardize the provider key on `anthropic`

`llm_provider` is a *vendor* identifier (there is a separate `llm_model` column),
so the value should be the vendor name. `anthropic` matches `openai` and
`deepseek`; `claude` is a model-family name and is the lone inconsistency. Audit
confirmed there is **no** provider/model conflation anywhere and **no** DB
constraint on the column — this is purely a spelling fix plus a data backfill.

Change `claude` → `anthropic` at every runtime + scraper site:

- `ingredients/src/ingredients/worker/providers_local.py` (`available_providers`
  entry + the `provider_id == "claude"` branch).
- `common/src/common/providers/cost.py` (`UNIT_COST_CENTS` key).
- `scraper/src/scraper/classify.py` (the `--provider` choices + the
  `provider_name == "claude"` branches). This renames the user-facing
  `--provider claude` flag to `--provider anthropic`.
- The worker tests that pin `claude` (`test_provider_registry.py`,
  `test_worker_provider_chain.py`).

Already `anthropic` (unchanged): `web/src/ui/runs/llmTiers.ts`, the SQL
`_estimate_cents`, and their tests.

**Data backfill:** a small migration runs
`update jobs set llm_provider = 'anthropic' where llm_provider = 'claude';`
(idempotent; safe if zero rows match).

**Verification:** after this, selecting the Claude tier and starting a run builds a
real `ClaudeProvider`, meters at the Anthropic rate, and the Start modal no longer
warns "no live worker can service 'anthropic'".

### 2. Cap Ollama output (`num_predict`)

Thinking is already disabled (`ollama.py` sends `"think": False`). Add a
`num_predict` cap (default **1024**) in the same `/api/generate` body so a single
pathological item cannot generate unbounded output up to the 120 s HTTP timeout.
The structured-JSON answers these stages produce are far under 1024 tokens, so the
cap never truncates a legitimate response.

### 3. Per-item token capture

Capture the token usage every provider already returns and persist it.

- **`ProviderResult`** (`common/src/common/llm/provider.py`) gains optional
  `prompt_tokens: int | None` and `completion_tokens: int | None`.
- Each provider populates them from its response: Ollama's
  `prompt_eval_count`/`eval_count`; the OpenAI/DeepSeek/Anthropic `usage` object.
  A provider that omits usage leaves them `None` (graceful).
- **Schema:** a migration adds `prompt_tokens int` and `completion_tokens int` to
  `job_items` (nullable), and `prompt_tokens`/`completion_tokens` roll-up columns
  to `jobs`, summed on finalize exactly as `cost_actual_cents` already is
  (`worker/loop.py`).
- The worker writes per-item token counts when it records an item's terminal
  state, attributing a packed call's usage across its items (simplest correct
  split: divide the call's usage evenly across the items in that pack).

This is pure telemetry — it does not feed the estimate. It enables throughput
(tokens/sec) and a cost cross-check later.

### 4. Duration history: one average per run kind

A read-only SQL view `job_duration_avg` computes, per
**`(stage, llm_provider, llm_model)`**, a single average seconds-per-item over
finished runs in a rolling **90-day** window:

```sql
select stage, llm_provider, llm_model,
       sum(extract(epoch from finished_at - started_at)) / nullif(sum(task_count), 0)
         as avg_seconds_per_item,
       count(*) as run_count,
       sum(task_count) as item_count
from jobs
where state = 'succeeded'
  and finished_at is not null and started_at is not null
  and task_count > 0
  and finished_at > now() - interval '90 days'
group by stage, llm_provider, llm_model;
```

(`succeeded` is the worker's terminal-success state — verified against the
`job_state` enum and `worker/loop.py:294`; not `done`, despite prose elsewhere.)
It is a ratio of sums (total elapsed ÷ total items), not a per-item statistic —
nothing to tune, robust to a few odd runs, and exactly the quantity the estimate
multiplies. Keying on **model** (unlike the cost estimate, which is
provider-only) matters because e.g. `qwen3:8b` vs `qwen3:14b` differ ~2×.

### 5. `estimate_run_seconds` RPC + bucket ladder

A SQL function `estimate_run_seconds(p_stage, p_provider, p_model, p_items)`
returns `{ seconds numeric, bucket text, source text }`:

```
seconds = p_items × avg_seconds_per_item(p_stage, p_provider, p_model)
```

**Hierarchical backoff** when a bucket has too little history
(`run_count < 3`): `(stage, provider, model)` → `(stage, provider)` →
`(stage)` → a **seed constant** (see below). `source` reports which level
answered (`'model'|'provider'|'stage'|'seed'`) so the UI can hedge low-confidence
estimates ("rough estimate").

**Seed constants** — a small in-function table of seconds-per-item, calibrated
from initial throughput measurements (post-`think:false`), used only until real
history accumulates. Deliberately coarse; overridden by history within a few runs:

| provider | seed s/item | basis |
|---|---|---|
| ollama · qwen3:14b | 1.5 | measured ~29 tok/s decode, ~200 out tok / 10-item pack |
| ollama · qwen3:8b | 0.7 | measured ~52 tok/s decode |
| deepseek / openai / anthropic | 0.5 | published ~90–105 tok/s, small packed calls |
| (extract stage, any provider) | 4.0 | unpacked, full-HTML input — least predictable |

**Bucket ladder** (deliberately coarse, per operator request):

| seconds | bucket label |
|---|---|
| < 60 | "under a minute" |
| 60 – 450 | "about 5 minutes" |
| 450 – 1200 | "about 10 minutes" |
| 1200 – 2700 | "about 30 minutes" |
| 2700 – 7200 | "about an hour" |
| ≥ 7200 | "a few hours" |

### 6. Pre-run estimate in the Start-confirm modal

`web/src/ui/runs/StartConfirmModal.tsx` calls `estimate_run_seconds` (a hook
mirroring the existing `useEstimate` cost hook) with the run's stage, tier
provider/model, and pending item count, and shows the bucket next to the cost
badge — e.g. **"~about 5 minutes"**. When `source = 'seed'` (or otherwise thin
history) it prefixes "rough estimate:". No range, no percentiles — one line.

### 7. Live "time remaining" ticker in the cockpit

`web/src/ui/runs/RunCockpit.tsx` already polls the run header and computes
`pct = done / total`. Add:

- **Elapsed** since `started_at` (humanized, like the existing `ago()` helper).
- **Estimated remaining** = `(elapsed / done) × (total − done)`, recomputed each
  poll from the running job's own counters — self-correcting, needs no history.
  Rendered through the same bucket ladder ("about 5 min left").
- **Before the first item completes** (`done = 0`), fall back to the pre-run
  `estimate_run_seconds` value so the ticker isn't blank at the start.

The ladder lives in one shared TS helper (`bucketSeconds`) used by both the modal
and the cockpit.

## Testing

- **Naming (Python):** worker registry tests updated to assert `anthropic` builds
  `ClaudeProvider` and appears in `available_providers`; `UNIT_COST_CENTS` keyed
  `anthropic`; scraper `--provider anthropic` selects the Anthropic path. A test
  asserts a `jobs` row with `llm_provider='anthropic'` yields a live provider end
  to end (guards against re-introducing the split).
- **Backfill:** a migration test (or `test_run_rpcs`-style check) that a
  pre-existing `claude` row becomes `anthropic`.
- **Token capture:** unit test per provider that a mocked response with usage
  populates `ProviderResult.{prompt,completion}_tokens`, and one worker test that
  the per-item and rolled-up `jobs` token columns are written on finalize.
- **num_predict:** assert the `/api/generate` body carries `num_predict` alongside
  `think: false`.
- **estimate_run_seconds (SQL):** table-driven — exact-match history returns the
  averaged seconds; backoff falls through model→provider→stage→seed; empty
  history uses the seed; bucket boundaries map to the right labels
  (`test_run_rpcs.py` style).
- **bucketSeconds (TS):** unit tests on the ladder boundaries.
- **UI:** `StartConfirmModal.test.tsx` shows the bucket + "rough estimate" on seed
  source; `RunCockpit.test.tsx` shows elapsed + remaining while running and the
  pre-run fallback at `done = 0`.

## Expected result

- Claude runs actually run (and price) correctly; one provider vocabulary
  (`anthropic`) across worker, SQL, UI, cost table, and scraper.
- Ollama calls are bounded (`think: false` + `num_predict`).
- Every LLM item records its token usage; `jobs` carries token roll-ups.
- The Start modal shows a rough time bucket beside the cost; the cockpit shows a
  live, self-correcting "time remaining" — both coarse and honest, degrading to a
  labeled "rough estimate" when history is thin.

## Ordering

1. Provider-name standardization + backfill migration (independent; unblocks
   correct Claude timing data going forward).
2. `num_predict` cap (independent, trivial).
3. Token capture: `ProviderResult` fields → provider population → `job_items` /
   `jobs` columns + roll-up.
4. `job_duration_avg` view.
5. `estimate_run_seconds` RPC + seed table + `bucketSeconds` helper.
6. Start-modal estimate.
7. Cockpit ticker.

Migrations are timestamped after `20260804090000` (the #109 audit migration).

## Alternatives considered

- **Percentile / p10–p90 range estimate.** Rejected as more than the operator
  wants; a single averaged bucket is simpler and sufficient. The average already
  absorbs load variance.
- **Analytical "100% LLM" ceiling** ("up to N min if every item hits the model").
  Cheap to add (`ceil(N/10)` calls × seed latency) and was discussed, but dropped
  from v1 to keep the modal to one honest number; the historical average is the
  better default. Can be added later as a secondary line if wanted.
- **Standardize on `claude` instead of `anthropic`.** Fewer runtime edits, but
  `claude` is a model-family name; `anthropic` keeps `llm_provider` meaning
  "vendor" consistently. Rejected.
- **Per-`job_item` duration sampling** instead of job-level `elapsed ÷ task_count`.
  More samples, but pack-of-10 timing can attribute a whole pack window to each
  item; the job-level ratio is assumption-free and matches what we multiply.
- **Tokens as an estimate input** (predict duration from predicted tokens).
  Rejected — output-token count is exactly the unpredictable quantity; measuring
  wall-clock outcomes sidesteps it.
