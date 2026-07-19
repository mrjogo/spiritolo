import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../supabase';
import { useRpc } from '../hooks/useRpc';
import { findTier, DEFAULT_LLM_TIER, type LlmTier } from './llmTiers';

// The lifecycle states a run (a `jobs` row) moves through, from the queue
// selection UI's point of view.
export type RunState = 'draft' | 'queued' | 'claimed' | 'running' | 'done' | 'failed';

// One row from the `runs` read view (a projection over `jobs` + item roll-ups).
// The write path is the RPC set below; this is the read side only.
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
}

const RUN_SELECT =
  'id, stage, state, llm_provider, llm_model, task_count, ' +
  'flagged_count, never_run_count, failed_count, cost_estimate_cents, ' +
  'max_cost_cents, created_at, created_by';

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
      const { data, error } = await supabase
        .from('runs')
        .select(RUN_SELECT)
        .eq('id', jobId)
        .maybeSingle();
      if (error) throw error;
      return (data as RunHeader | null) ?? null;
    },
    enabled: jobId != null,
  });

  const run = query.data ?? null;
  const tier = findTier(run?.llm_provider, run?.llm_model) ?? DEFAULT_LLM_TIER;

  return {
    run,
    tier,
    status: query.isError ? 'error' : query.isPending ? 'loading' : 'loaded',
  };
}

// --- Run-level mutations (the RPC write path) -----------------------------

type CreateRunArgs = { stage: string };
type SetRunLlmArgs = { job_id: number; provider: string; model: string };
type StartRunArgs = { job_id: number; max_cost_cents: number };

/** create_run(stage) -> bigint job id. */
export function useCreateRun() {
  return useRpc<CreateRunArgs, number>('create_run', { invalidate: [['runs']] });
}

/** set_run_llm(job_id, provider, model). */
export function useSetRunLlm(jobId: number) {
  return useRpc<SetRunLlmArgs, void>('set_run_llm', { invalidate: [['run', jobId]] });
}

/** start_run(job_id, max_cost_cents). */
export function useStartRun(jobId: number) {
  return useRpc<StartRunArgs, void>('start_run', { invalidate: [['run', jobId], ['runs']] });
}
