import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';

// GET /api/ops/executor — the in-process executor's liveness and what it can run.
export interface ExecutorHealth {
  alive: boolean;
  disabled?: boolean;
  worker_id?: string;
  current_job_id?: number | null;
  last_tick_age_seconds?: number | null;
  jobs_run?: number;
  last_error?: string | null;
  providers?: string[];
  stages?: string[];
}

// The shape the runs UI consumes. Kept from the worker_status days: "freshest"
// is now simply the executor thread of the process serving this page.
export interface WorkerRow {
  worker_id: string;
  last_seen: string;
  providers: string[];
  stages: string[];
}

export interface WorkerHealth {
  freshest: WorkerRow | null;
  /** Seconds since the executor last ticked (Infinity if it is not running). */
  ageSeconds: number;
  /** True when the executor thread is not alive (or the health probe failed). */
  stale: boolean;
  /** Providers the executor can build a client for (for Start pre-flight). */
  liveProviders: string[];
  loading: boolean;
}

const POLL_MS = 5000;

export function useWorkerHealth(): WorkerHealth {
  const query = useQuery({
    queryKey: ['executorHealth'],
    queryFn: () => api<ExecutorHealth>('/api/ops/executor'),
    refetchInterval: POLL_MS,
    staleTime: 0,
  });

  const h = query.data;
  if (!h || !h.alive) {
    return { freshest: null, ageSeconds: Infinity, stale: true, liveProviders: [], loading: query.isPending };
  }
  const ageSeconds = h.last_tick_age_seconds ?? 0;
  // Anchor "last seen" on when the probe result arrived (query state, so the
  // render stays pure) rather than on the wall clock at render time.
  const freshest: WorkerRow = {
    worker_id: h.worker_id ?? 'executor',
    last_seen: new Date(query.dataUpdatedAt - ageSeconds * 1000).toISOString(),
    providers: h.providers ?? [],
    stages: h.stages ?? [],
  };
  return { freshest, ageSeconds, stale: false, liveProviders: freshest.providers, loading: false };
}
