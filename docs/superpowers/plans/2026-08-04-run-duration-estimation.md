# Run Duration Estimation + Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give operators a rough, honest run-duration estimate before a run (Start modal) and while it runs (cockpit ticker), backed by per-item token/timing telemetry, and fix the `anthropic`/`claude` provider-key split.

**Architecture:** History-driven, not analytical — a SQL view averages `elapsed ÷ items` per `(stage, provider, model)`; an RPC multiplies that by the pending count and the UI snaps it to a coarse bucket. Token counts already returned by every provider are captured per `job_item` and rolled up to `jobs`. The provider-key rename is a pure value change (no DB constraint exists).

**Tech Stack:** Python 3.11 (uv, pytest), Postgres/Supabase migrations, React + TS + Vitest.

## Global Constraints

- Provider key for Anthropic is **`anthropic`** everywhere (vendor name); `llm_provider` always means vendor, `llm_model` always means model. Copy verbatim.
- New migrations are timestamped **after** `20260804090000` (the #109 audit migration). Use `20260804100000` (naming backfill), `20260804100100` (token columns), `20260804100200` (duration view + RPC).
- Terminal-success job state literal is **`'succeeded'`** (verified: `job_state` enum + `worker/loop.py:294`), not `'done'`.
- Bucket ladder (seconds → label), used by exactly one shared TS helper: `<60` → "under a minute"; `60–450` → "about 5 minutes"; `450–1200` → "about 10 minutes"; `1200–2700` → "about 30 minutes"; `2700–7200` → "about an hour"; `≥7200` → "a few hours".
- Run Python from `ingredients/` / `common/` via `cd ingredients && uv run …`; scraper via `cd scraper && uv run …`; web via `cd web && npm …`. DB tests need `TEST_DB_URL` set (skip cleanly otherwise).

## Task dependency / parallelism map

- **Wave 1 (independent — run in parallel, isolated worktrees):** Task 1 (naming), Task 2 (Python LLM providers: `num_predict` + token capture), Task 4 (SQL view + RPC), Task 5 (bucketSeconds helper).
- **Wave 2 (after Wave 1):** Task 3 (worker token threading — needs Task 2's `ProviderResult` fields), Task 6 (Start modal — needs Tasks 4+5), Task 7 (cockpit ticker — needs Tasks 4+5). These three are file-disjoint and may run in parallel.

File-disjointness: Task 1 owns `worker/providers_local.py`, `providers/cost.py`, `scraper/classify.py`; Task 2 owns `common/llm/*`; Task 3 owns `worker/providers.py`, `pipeline/stages/base.py`, `worker/loop.py`, `ledger`; Task 6 owns `StartConfirmModal.tsx` + a new hook; Task 7 owns `RunCockpit.tsx`. No two concurrent tasks touch the same file.

---

### Task 1: Standardize the Anthropic provider key on `anthropic`

**Files:**
- Modify: `ingredients/src/ingredients/worker/providers_local.py:100` and `:141` (+ docstring `:123`)
- Modify: `common/src/common/providers/cost.py:19`
- Modify: `scraper/src/scraper/classify.py:114`, `:171`
- Modify tests: `ingredients/tests/test_provider_registry.py`, `ingredients/tests/test_worker_provider_chain.py`
- Create: `supabase/migrations/20260804100000_provider_key_anthropic_backfill.sql`

**Interfaces:**
- Produces: worker `build_provider_for_run("anthropic", …)` builds `ClaudeProvider`; `available_providers()` lists `"anthropic"` when `ANTHROPIC_API_KEY` is set; `UNIT_COST_CENTS["anthropic"] == 2`; scraper `--provider anthropic`.

- [ ] **Step 1: Update the worker registry tests to expect `anthropic` (failing).** In `test_provider_registry.py`, change the Claude case so `build_provider_for_run("anthropic", …)` returns a `ClaudeProvider` and `"anthropic"` (not `"claude"`) appears in `available_providers({"ANTHROPIC_API_KEY": "k"})`. In `test_worker_provider_chain.py`, change the two `llm_provider:"claude"` / `available_providers` assertions to `"anthropic"`.

- [ ] **Step 2: Run tests, verify they fail.** `cd ingredients && uv run --extra dev pytest tests/test_provider_registry.py tests/test_worker_provider_chain.py -q` → FAIL (still keyed `claude`).

- [ ] **Step 3: Rename in source.** In `providers_local.py`: line 100 `out.append("claude")` → `out.append("anthropic")`; line 141 `if provider_id == "claude"` → `if provider_id == "anthropic"`; update the docstring mention (`:123`) `openai`/`claude`/`deepseek` → `openai`/`anthropic`/`deepseek`. In `cost.py:19` `"claude": 2,` → `"anthropic": 2,`. In `classify.py:114` choices `["ollama", "claude", "openai"]` → `["ollama", "anthropic", "openai"]`; `:171` `if provider_name == "claude"` → `if provider_name == "anthropic"` (update the flag help text on `:121` similarly: "For anthropic pass e.g. claude-haiku-4-5").

- [ ] **Step 4: Run tests, verify they pass.** Same command as Step 2 → PASS. Also `cd scraper && uv run pytest -q` if scraper has classify provider tests.

- [ ] **Step 5: Write the backfill migration.**

```sql
-- 20260804100000_provider_key_anthropic_backfill.sql
-- Standardize the Anthropic provider key on the vendor name `anthropic`
-- (was split: UI/SQL used `anthropic`, worker used `claude`). Idempotent;
-- no-op when zero rows carry the old spelling.
update public.jobs set llm_provider = 'anthropic' where llm_provider = 'claude';
```

- [ ] **Step 6: Apply + verify the migration.** From the Supabase host: `supabase migration up --include-all`, then `supabase migration list` shows it applied. (If `TEST_DB_URL` is set, the ingredients conftest applies it to the test DB on next pytest.)

- [ ] **Step 7: Commit.**

```bash
git add ingredients/src/ingredients/worker/providers_local.py common/src/common/providers/cost.py scraper/src/scraper/classify.py ingredients/tests/test_provider_registry.py ingredients/tests/test_worker_provider_chain.py supabase/migrations/20260804100000_provider_key_anthropic_backfill.sql
git commit -m "Standardize Anthropic provider key on 'anthropic' across worker, cost, scraper + backfill"
```

---

### Task 2: Ollama output cap + token capture on every provider

**Files:**
- Modify: `common/src/common/llm/provider.py` (`ProviderResult` fields)
- Modify: `common/src/common/llm/ollama.py`, `openai.py`, `claude.py` (populate tokens; ollama adds `num_predict`)
- Test: `common/tests/test_provider_ollama.py` (create if absent), `common/tests/test_provider_openai.py`, `common/tests/test_provider_claude.py`

**Interfaces:**
- Produces: `ProviderResult(raw_text, model_id, prompt_tokens: int | None = None, completion_tokens: int | None = None)`. All four providers set the two token fields when the response carries usage; `None` when absent. (DeepSeek inherits `OpenAIProvider.resolve`, so it's covered by the OpenAI change.)

- [ ] **Step 1: Add the token fields to `ProviderResult` (failing test first).** In `common/tests/test_provider_ollama.py` add:

```python
def test_ollama_captures_token_counts():
    from common.llm.ollama import OllamaProvider
    from unittest.mock import Mock
    resp = Mock(status_code=200)
    resp.json.return_value = {"response": "{}", "prompt_eval_count": 142, "eval_count": 188}
    client = Mock(); client.post.return_value = resp
    r = OllamaProvider(client=client).resolve(system_prompt="", user_prompt="x")
    assert r.prompt_tokens == 142 and r.completion_tokens == 188
```

- [ ] **Step 2: Run, verify fail.** `cd common && uv run --extra dev pytest tests/test_provider_ollama.py::test_ollama_captures_token_counts -q` → FAIL (`ProviderResult` has no `prompt_tokens`).

- [ ] **Step 3: Extend `ProviderResult`.** In `provider.py`:

```python
@dataclass(frozen=True)
class ProviderResult:
    """Raw provider output. Caller parses with the flow's parse_response."""
    raw_text: str
    model_id: str           # e.g. 'claude-haiku-4-5', 'qwen3:14b', 'gpt-5-mini'
    prompt_tokens: int | None = None      # input tokens the provider billed, if reported
    completion_tokens: int | None = None  # output tokens generated, if reported
```

- [ ] **Step 4: Ollama — read usage + cap output.** In `ollama.py`, add `DEFAULT_NUM_PREDICT = 1024` near the other constants, add `"num_predict": DEFAULT_NUM_PREDICT` to the `_generate` JSON body (alongside `"think": False`), and change `resolve` to read counts:

```python
    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        resp = self._generate(system_prompt, user_prompt)
        if getattr(resp, "status_code", None) == 404 and self.auto_pull:
            self._pull()
            resp = self._generate(system_prompt, user_prompt)
        resp.raise_for_status()
        body = resp.json()
        return ProviderResult(
            raw_text=body.get("response", ""),
            model_id=self.model_id,
            prompt_tokens=body.get("prompt_eval_count"),
            completion_tokens=body.get("eval_count"),
        )
```

- [ ] **Step 5: OpenAI (covers DeepSeek) — read `resp.usage`.** In `openai.py` `resolve`, after computing `text`:

```python
        usage = getattr(resp, "usage", None)
        return ProviderResult(
            raw_text=text,
            model_id=self.model_id,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
        )
```

- [ ] **Step 6: Claude — read `msg.usage`.** In `claude.py` `resolve`:

```python
        usage = getattr(msg, "usage", None)
        return ProviderResult(
            raw_text=text,
            model_id=self.model_id,
            prompt_tokens=getattr(usage, "input_tokens", None),
            completion_tokens=getattr(usage, "output_tokens", None),
        )
```

- [ ] **Step 7: Add the `num_predict` + openai/claude usage tests.** Add to `test_provider_ollama.py`:

```python
def test_ollama_sends_num_predict_cap():
    from common.llm.ollama import OllamaProvider, DEFAULT_NUM_PREDICT
    from unittest.mock import Mock
    resp = Mock(status_code=200); resp.json.return_value = {"response": "{}"}
    client = Mock(); client.post.return_value = resp
    OllamaProvider(client=client).resolve(system_prompt="", user_prompt="x")
    body = client.post.call_args.kwargs["json"]
    assert body["num_predict"] == DEFAULT_NUM_PREDICT and body["think"] is False
```

In `test_provider_openai.py` / `test_provider_claude.py`, add a case asserting a mocked response with a `usage` object populates `ProviderResult.prompt_tokens` / `completion_tokens` (OpenAI `prompt_tokens`/`completion_tokens`; Claude `input_tokens`/`output_tokens`).

- [ ] **Step 8: Run all provider tests, verify pass.** `cd common && uv run --extra dev pytest tests/ -q` → PASS.

- [ ] **Step 9: Commit.**

```bash
git add common/src/common/llm/provider.py common/src/common/llm/ollama.py common/src/common/llm/openai.py common/src/common/llm/claude.py common/tests/
git commit -m "Capture per-call token usage in ProviderResult; cap Ollama output (num_predict)"
```

---

### Task 3: Persist token counts per job_item and roll up to jobs

**Depends on Task 2** (`ProviderResult.prompt_tokens` / `completion_tokens`).

**Files:**
- Create: `supabase/migrations/20260804100100_job_item_tokens.sql`
- Modify: `ingredients/src/ingredients/worker/providers.py` (`_run_llm` — attribute usage across a pack's items)
- Modify: the ledger writer behind `pipeline/stages/base.py:record` / `record_many` (search `def record_run`/`record_runs` — likely `ingredients/src/ingredients/reviews/ledger.py`) to accept + write `prompt_tokens` / `completion_tokens`
- Modify: `ingredients/src/ingredients/pipeline/stages/base.py` (`record` / `record_node` / `record_many` gain the two optional kwargs, passed through)
- Modify: `ingredients/src/ingredients/worker/loop.py:196-206` (finalize roll-up)
- Test: `ingredients/tests/test_worker_provider_chain.py`, `ingredients/tests/test_run_rpcs.py` (or the existing finalize test)

**Interfaces:**
- Consumes: `ProviderResult.prompt_tokens`, `.completion_tokens` (Task 2).
- Produces: `job_items.prompt_tokens int`, `job_items.completion_tokens int`; `jobs.prompt_tokens int`, `jobs.completion_tokens int`; `base.record(..., prompt_tokens=None, completion_tokens=None)`; per-pack even split of a call's usage.

- [ ] **Step 1: Migration for the columns.**

```sql
-- 20260804100100_job_item_tokens.sql
alter table public.job_items add column if not exists prompt_tokens int;
alter table public.job_items add column if not exists completion_tokens int;
alter table public.jobs add column if not exists prompt_tokens int;
alter table public.jobs add column if not exists completion_tokens int;
```

- [ ] **Step 2: Apply the migration.** `supabase migration up --include-all` on the host (test DB picks it up via conftest).

- [ ] **Step 3: Write the failing chain test.** In `test_worker_provider_chain.py`, drive `_run_llm` (or the chain) with a fake provider whose `resolve` returns `ProviderResult(raw_text=..., model_id=..., prompt_tokens=100, completion_tokens=40)` over a pack of 4 items, and assert each resolved item is recorded with `prompt_tokens == 25` and `completion_tokens == 10` (even split, integer division; remainder to the first item is acceptable — assert the *sum* equals the call usage).

- [ ] **Step 4: Run, verify fail.** `cd ingredients && uv run --extra dev pytest tests/test_worker_provider_chain.py -k token -q` → FAIL.

- [ ] **Step 5: Attribute usage in `_run_llm`.** After a pack's `provider.resolve(...)` returns, split `result.prompt_tokens` / `result.completion_tokens` evenly across the pack's item ids (`n = len(pack)`; `per = total // n`; give the remainder to the first item) and carry those per-item token counts alongside the existing per-item `cost_cents` / `model_id` into whatever structure the chain returns to the stage. (Read the existing return shape in `providers.py` — mirror how `cost_cents`/`model_id` already flow to `record`.)

- [ ] **Step 6: Thread through `base.record` + ledger.** Add `prompt_tokens: int | None = None` and `completion_tokens: int | None = None` params to `record`, `record_node`, `record_many` (base.py) and to `ledger.record_run` / `record_runs`, writing them into the `job_items` UPDATE/UPSERT column list next to `cost_cents` / `model_id`.

- [ ] **Step 7: Roll up on finalize.** In `loop.py` where `cost_actual_cents` is summed from `job_items` (around `:196-206`), add `sum(prompt_tokens)` / `sum(completion_tokens)` into the new `jobs.prompt_tokens` / `jobs.completion_tokens` columns in the same UPDATE.

- [ ] **Step 8: Run, verify pass.** `cd ingredients && uv run --extra dev pytest tests/test_worker_provider_chain.py -q` → PASS. Add/confirm a finalize test asserting the `jobs` roll-up equals the sum of its items' tokens.

- [ ] **Step 9: Commit.**

```bash
git add supabase/migrations/20260804100100_job_item_tokens.sql ingredients/src/ingredients/worker/providers.py ingredients/src/ingredients/pipeline/stages/base.py ingredients/src/ingredients/reviews/ledger.py ingredients/src/ingredients/worker/loop.py ingredients/tests/
git commit -m "Persist per-item token counts; roll up to jobs on finalize"
```

---

### Task 4: Duration history view + `estimate_run_seconds` RPC

**Files:**
- Create: `supabase/migrations/20260804100200_estimate_run_seconds.sql`
- Test: `ingredients/tests/test_run_rpcs.py` (new cases)

**Interfaces:**
- Produces: view `public.job_duration_avg(stage, llm_provider, llm_model, avg_seconds_per_item, run_count, item_count)`; RPC `public.estimate_run_seconds(p_stage text, p_provider text, p_model text, p_items int) returns jsonb` = `{"seconds": numeric, "source": text}` where `source ∈ {'model','provider','stage','seed'}`.

- [ ] **Step 1: Write the migration (view + function).**

```sql
-- 20260804100200_estimate_run_seconds.sql

-- Average wall-clock seconds-per-item per (stage, provider, model), over
-- SUCCEEDED runs in a rolling 90-day window. Ratio of sums (total elapsed ÷
-- total items) — assumption-free, robust to a few odd runs. Item count comes
-- from job_items (jobs has no task_count column). Powers estimate_run_seconds.
create or replace view public.job_duration_avg as
select j.stage, j.llm_provider, j.llm_model,
       sum(extract(epoch from j.finished_at - j.started_at))
         / nullif(sum(ic.n), 0)             as avg_seconds_per_item,
       count(*)                              as run_count,
       sum(ic.n)                             as item_count
from public.jobs j
join lateral (select count(*)::numeric as n from public.job_items ji
              where ji.job_id = j.id) ic on true
where j.state = 'succeeded'
  and j.started_at is not null and j.finished_at is not null
  and j.finished_at > now() - interval '90 days'
  and ic.n > 0
group by j.stage, j.llm_provider, j.llm_model;

-- Rough run-duration estimate: seconds-per-item (from history, else a seed
-- constant) × item count. Hierarchical backoff widens the sample when a precise
-- bucket is thin: (stage,provider,model) → (stage,provider) → (stage) → seed.
-- Returns {seconds, source}; the UI snaps `seconds` to a coarse bucket. Seeds
-- are post-`think:false` measurements, overridden once history accrues.
create or replace function public.estimate_run_seconds(
  p_stage text, p_provider text, p_model text, p_items int
) returns jsonb
language plpgsql stable security definer set search_path = '' as $$
declare v_spi numeric; v_src text;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  select avg_seconds_per_item into v_spi from public.job_duration_avg
   where stage = p_stage
     and llm_provider is not distinct from p_provider
     and llm_model    is not distinct from p_model
     and run_count >= 3;
  if v_spi is not null then v_src := 'model'; end if;

  if v_spi is null then
    select sum(avg_seconds_per_item * item_count) / nullif(sum(item_count), 0)
      into v_spi from public.job_duration_avg
     where stage = p_stage and llm_provider is not distinct from p_provider;
    if v_spi is not null then v_src := 'provider'; end if;
  end if;

  if v_spi is null then
    select sum(avg_seconds_per_item * item_count) / nullif(sum(item_count), 0)
      into v_spi from public.job_duration_avg where stage = p_stage;
    if v_spi is not null then v_src := 'stage'; end if;
  end if;

  if v_spi is null then
    v_spi := case
      when p_stage = 'extract-recipe' then 4.0
      when p_provider = 'ollama' and p_model = 'qwen3:8b' then 0.7
      when p_provider = 'ollama' then 1.5
      when p_provider in ('deepseek', 'openai', 'anthropic') then 0.5
      else 0.3
    end;
    v_src := 'seed';
  end if;

  return jsonb_build_object(
    'seconds', round((coalesce(p_items, 0) * v_spi)::numeric, 1),
    'source', v_src
  );
end;
$$;
```

- [ ] **Step 2: Apply migration.** `supabase migration up --include-all` on the host.

- [ ] **Step 3: Write RPC tests (require `TEST_DB_URL`).** In `test_run_rpcs.py`, mirroring the existing `_estimate_cents` tests: (a) empty history → `estimate_run_seconds('map-ingredient','ollama','qwen3:14b',100)` returns `source='seed'` and `seconds=150.0` (100 × 1.5); (b) insert ≥3 succeeded `jobs` + `job_items` for that key with a known elapsed → `source='model'` and `seconds` = items × observed avg; (c) extract seed is 4.0/item.

- [ ] **Step 4: Run, verify pass.** `cd ingredients && uv run --extra dev pytest tests/test_run_rpcs.py -k estimate_run_seconds -q` → PASS (or SKIP if `TEST_DB_URL` unset — note that in the commit).

- [ ] **Step 5: Commit.**

```bash
git add supabase/migrations/20260804100200_estimate_run_seconds.sql ingredients/tests/test_run_rpcs.py
git commit -m "Add job_duration_avg view + estimate_run_seconds RPC (history-driven, seed fallback)"
```

---

### Task 5: `bucketSeconds` shared TS helper

**Files:**
- Create: `web/src/ui/runs/bucketSeconds.ts`
- Test: `web/src/ui/runs/bucketSeconds.test.ts`

**Interfaces:**
- Produces: `bucketSeconds(seconds: number): string` — maps to the Global-Constraints ladder.

- [ ] **Step 1: Write the failing test.**

```ts
import { describe, it, expect } from 'vitest';
import { bucketSeconds } from './bucketSeconds';

describe('bucketSeconds', () => {
  it('maps the ladder boundaries', () => {
    expect(bucketSeconds(0)).toBe('under a minute');
    expect(bucketSeconds(59)).toBe('under a minute');
    expect(bucketSeconds(60)).toBe('about 5 minutes');
    expect(bucketSeconds(449)).toBe('about 5 minutes');
    expect(bucketSeconds(450)).toBe('about 10 minutes');
    expect(bucketSeconds(1200)).toBe('about 30 minutes');
    expect(bucketSeconds(2700)).toBe('about an hour');
    expect(bucketSeconds(7200)).toBe('a few hours');
  });
});
```

- [ ] **Step 2: Run, verify fail.** `cd web && npm test -- bucketSeconds` → FAIL (module missing).

- [ ] **Step 3: Implement.**

```ts
// Snap an estimated duration (seconds) to a deliberately coarse bucket label.
// One source of truth shared by the Start modal and the cockpit ticker.
export function bucketSeconds(seconds: number): string {
  if (seconds < 60) return 'under a minute';
  if (seconds < 450) return 'about 5 minutes';
  if (seconds < 1200) return 'about 10 minutes';
  if (seconds < 2700) return 'about 30 minutes';
  if (seconds < 7200) return 'about an hour';
  return 'a few hours';
}
```

- [ ] **Step 4: Run, verify pass.** `cd web && npm test -- bucketSeconds` → PASS.

- [ ] **Step 5: Commit.**

```bash
git add web/src/ui/runs/bucketSeconds.ts web/src/ui/runs/bucketSeconds.test.ts
git commit -m "Add bucketSeconds duration-label helper"
```

---

### Task 6: Pre-run time estimate in the Start-confirm modal

**Depends on Tasks 4 (RPC) + 5 (helper).**

**Files:**
- Create: `web/src/ui/runs/useEstimateSeconds.ts`
- Modify: `web/src/ui/runs/StartConfirmModal.tsx`
- Test: `web/src/ui/runs/StartConfirmModal.test.tsx`

**Interfaces:**
- Consumes: `estimate_run_seconds` RPC (Task 4), `bucketSeconds` (Task 5).
- Produces: `useEstimatedRunSeconds(stage, provider, model, items, enabled): { seconds: number; source: string } | null`.

- [ ] **Step 1: Write the hook (mirror `useEstimate.ts`).**

```ts
import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../supabase';

// Live rough time estimate for a run: seconds-per-item (from history, else a
// seed) × item count, returned as { seconds, source }. Mirrors
// useEstimatedRunCents — pricing/timing math both live server-side.
export function useEstimatedRunSeconds(
  stage: string | null | undefined,
  provider: string | null | undefined,
  model: string | null | undefined,
  items: number | null | undefined,
  enabled: boolean,
): { seconds: number; source: string } | null {
  const q = useQuery({
    queryKey: ['estimateRunSeconds', stage, provider, model, items],
    enabled: enabled && stage != null && provider != null && model != null && items != null,
    queryFn: async () => {
      const { data, error } = await supabase.rpc('estimate_run_seconds', {
        p_stage: stage, p_provider: provider, p_model: model, p_items: items,
      });
      if (error) throw error;
      return data as { seconds: number; source: string };
    },
  });
  return q.data ?? null;
}
```

- [ ] **Step 2: Write the failing modal test.** In `StartConfirmModal.test.tsx`, render with a mocked `useEstimatedRunSeconds` returning `{ seconds: 150, source: 'seed' }` and assert the modal shows "about 5 minutes" and a "rough estimate" qualifier (because `source === 'seed'`).

- [ ] **Step 3: Run, verify fail.** `cd web && npm test -- StartConfirmModal` → FAIL.

- [ ] **Step 4: Wire it into the modal.** Import `useEstimatedRunSeconds` + `bucketSeconds`; call it with `run.stage, tier.provider, tier.model, run.task_count, run.cost_estimate_cents == null`. Add a line inside `runs-estbox` next to the cost:

```tsx
{est && (
  <div className="runs-progress__meta">
    {est.source === 'model' || est.source === 'provider' ? '' : 'rough estimate: '}
    ~ {bucketSeconds(est.seconds)}
  </div>
)}
```

- [ ] **Step 5: Run, verify pass.** `cd web && npm test -- StartConfirmModal` → PASS.

- [ ] **Step 6: Commit.**

```bash
git add web/src/ui/runs/useEstimateSeconds.ts web/src/ui/runs/StartConfirmModal.tsx web/src/ui/runs/StartConfirmModal.test.tsx
git commit -m "Show rough time estimate in the Start-confirm modal"
```

---

### Task 7: Live "time remaining" ticker in the run cockpit

**Depends on Tasks 4 (RPC, for the pre-first-item fallback) + 5 (helper).**

**Files:**
- Modify: `web/src/ui/runs/RunCockpit.tsx`
- Test: `web/src/ui/runs/RunCockpit.test.tsx`

**Interfaces:**
- Consumes: `RunHeader.started_at` (exists), `bucketSeconds`, `useEstimatedRunSeconds`.

- [ ] **Step 1: Write the failing test.** In `RunCockpit.test.tsx`, render a `running` run with `started_at` 100s ago, `task_count: 100`, `items_applied: 25` (done=25), and assert the progress card shows a "~ about 5 minutes left" style remaining label (ETR = (100/25)×75 = 300s → "about 5 minutes"). Add a second case with `done = 0` asserting it falls back to the `useEstimatedRunSeconds` value.

- [ ] **Step 2: Run, verify fail.** `cd web && npm test -- RunCockpit` → FAIL.

- [ ] **Step 3: Add the ticker.** In `RunCockpit.tsx`, after `pct`:

```tsx
const elapsedSec = run.started_at ? Math.max(0, (Date.now() - new Date(run.started_at).getTime()) / 1000) : 0;
const preRun = useEstimatedRunSeconds(run.stage, run.llm_provider, run.llm_model, total, active && done === 0);
const etrSec = done > 0 ? (elapsedSec / done) * (total - done) : preRun?.seconds ?? null;
```

Render inside the Progress `runs-cockcard`, only while `active`:

```tsx
{active && etrSec != null && (
  <div className="runs-progress__meta">≈ {bucketSeconds(etrSec)} left</div>
)}
```

Add the imports for `bucketSeconds` and `useEstimatedRunSeconds`. (The cockpit already re-renders on each header poll while active, so `Date.now()`-based elapsed advances without a separate timer; a 1s `setInterval` is optional polish, out of scope.)

- [ ] **Step 4: Run, verify pass.** `cd web && npm test -- RunCockpit` → PASS.

- [ ] **Step 5: Commit.**

```bash
git add web/src/ui/runs/RunCockpit.tsx web/src/ui/runs/RunCockpit.test.tsx
git commit -m "Show live estimated time-remaining in the run cockpit"
```

---

## Final integration

- [ ] **Full suites:** `cd ingredients && uv run --extra dev pytest -q`; `cd common && uv run --extra dev pytest -q`; `cd scraper && uv run pytest -q`; `cd web && npm test`.
- [ ] **Regenerate `web/package-lock.json` under Node 20 only if deps changed** (they don't here — no new npm packages; `@tanstack/react-query` + `vitest` already present).
- [ ] **Migrations forward-apply clean:** on the Supabase host `supabase db reset --yes` replays all migrations including the three new ones without error.
- [ ] **PR** against `main`, per CLAUDE.md (one paragraph + ≤8 bullets, no sections/test-plan).

## Self-review notes

- Spec §1 → Task 1; §2 (num_predict) → Task 2 Step 4; §3 (tokens) → Tasks 2+3; §4 (view) + §5 (RPC/seeds/buckets) → Tasks 4+5; §6 (modal) → Task 6; §7 (ticker) → Task 7. No spec section unmapped.
- The analytical "100% LLM ceiling" was deliberately dropped in the spec (Alternatives) — intentionally absent here.
- Type consistency: `estimate_run_seconds` returns `{seconds, source}` in Task 4, consumed with that exact shape in Tasks 6 & 7; `bucketSeconds(seconds: number): string` defined in Task 5, used in 6 & 7; `ProviderResult` token fields defined in Task 2, consumed in Task 3.
