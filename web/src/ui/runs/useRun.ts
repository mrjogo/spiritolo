import { useQuery } from '@tanstack/react-query';
import { api, ApiError } from '../../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { findTier, DEFAULT_LLM_TIER, type LlmTier } from './llmTiers';

// The lifecycle states a run (a `jobs` row) moves through, from the queue
// selection UI's point of view.
export type RunState =
  | 'draft'
  | 'queued'
  | 'running'
  | 'cancelling'
  | 'done'
  | 'failed'
  | 'cancelled';

// Active = a worker is (or should be) working this run, so the cockpit polls
// for live progress and offers Cancel.
const ACTIVE_STATES: readonly RunState[] = ['queued', 'running', 'cancelling'];
export function isActiveRun(state: RunState): boolean {
  return ACTIVE_STATES.includes(state);
}
// Finished = eligible for retry-residue.
const FINISHED_STATES: readonly RunState[] = ['done', 'failed', 'cancelled'];
export function isFinishedRun(state: RunState): boolean {
  return FINISHED_STATES.includes(state);
}

// One row from the `runs` read view (a projection over `jobs` + item roll-ups),
// served by GET /api/ops/runs/:id. The write path is the mutation set below.
export interface RunHeader {
  id: number;
  stage: string;
  state: RunState;
  llm_provider: string | null;
  llm_model: string | null;
  task_count: number;
  /** Composition of the task set, for the estimate + confirm modal. */
  flagged_count: number;
  never_run_count: number;
  failed_count: number;
  cost_estimate_cents: number | null;
  max_cost_cents: number | null;
  created_at: string | null;
  created_by: string | null;
  // --- cockpit fields (live/terminal) ---
  cost_actual_cents: number | null;
  error_code: string | null;
  error_detail: string | null;
  worker_id: string | null;
  last_heartbeat: string | null;
  started_at: string | null;
  finished_at: string | null;
  /** Per-item-state progress counts (sum to task_count). */
  items_pending: number;
  items_applied: number;
  items_flagged: number;
  items_failed: number;
}

// While a run is active the cockpit polls the header so progress / cost /
// heartbeat update without a manual refresh.
const ACTIVE_POLL_MS = 2500;

export interface UseRunResult {
  run: RunHeader | null;
  tier: LlmTier;
  status: 'loading' | 'error' | 'loaded';
}

// Reads one run's header from the `runs` view. The selected LLM tier is
// resolved back to an LlmTier (falling back to the free default) so callers
// render the picker + estimate without re-deriving the mapping.
export function useRun(jobId: number | null): UseRunResult {
  const query = useQuery({
    queryKey: ['run', jobId],
    queryFn: async () => {
      try {
        return await api<RunHeader>(`/api/ops/runs/${jobId}`);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null;
        throw err;
      }
    },
    enabled: jobId != null,
    // Live-poll while the run is in flight; stop once it's terminal or draft.
    refetchInterval: (q) => {
      const s = (q.state.data as RunHeader | null)?.state;
      return s && isActiveRun(s) ? ACTIVE_POLL_MS : false;
    },
  });

  const run = query.data ?? null;
  const tier = findTier(run?.llm_provider, run?.llm_model) ?? DEFAULT_LLM_TIER;

  return {
    run,
    tier,
    status: query.isError ? 'error' : query.isPending ? 'loading' : 'loaded',
  };
}

// --- Run-level mutations (the write path) ---------------------------------

type CreateRunArgs = { stage: string };
type SetRunLlmArgs = { job_id: number; provider: string; model: string };
type StartRunArgs = { job_id: number; max_cost_cents: number };

/** POST /api/ops/runs {stage} -> job id. */
export function useCreateRun() {
  return useApiMutation<CreateRunArgs, number>(
    async (a) => (await api<{ id: number }>('/api/ops/runs', { body: a })).id,
    { invalidate: [['runs'], ['pagedQuery', 'runs']] },
  );
}

/** POST /api/ops/runs/:id/llm {provider, model}. */
export function useSetRunLlm(jobId: number) {
  return useApiMutation<SetRunLlmArgs, void>(
    async (a) => { await api(`/api/ops/runs/${a.job_id}/llm`, { body: { provider: a.provider, model: a.model } }); },
    { invalidate: [['run', jobId]] },
  );
}

/** POST /api/ops/runs/:id/start {max_cost_cents}. */
export function useStartRun(jobId: number) {
  return useApiMutation<StartRunArgs, void>(
    async (a) => { await api(`/api/ops/runs/${a.job_id}/start`, { body: { max_cost_cents: a.max_cost_cents } }); },
    { invalidate: [['run', jobId], ['runs'], ['pagedQuery', 'runs']] },
  );
}

/** POST /api/ops/runs/:id/cancel: stop a draft/queued run outright, or ask a running one to stop. */
export function useCancelRun(jobId: number) {
  return useApiMutation<{ job_id: number }, void>(
    async (a) => { await api(`/api/ops/runs/${a.job_id}/cancel`, { method: 'POST' }); },
    { invalidate: [['run', jobId], ['runs'], ['pagedQuery', 'runs']] },
  );
}

/** POST /api/ops/runs/:id/retry: re-drive a finished run's residue (failed + unprocessed). */
export function useRetryRun(jobId: number) {
  return useApiMutation<{ job_id: number }, void>(
    async (a) => { await api(`/api/ops/runs/${a.job_id}/retry`, { method: 'POST' }); },
    { invalidate: [['run', jobId], ['runs'], ['pagedQuery', 'runs']] },
  );
}
