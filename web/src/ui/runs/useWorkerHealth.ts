import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../supabase';

// One row of the worker_status table — a worker's liveness + what it can run.
export interface WorkerRow {
  worker_id: string;
  last_seen: string;
  providers: string[];
  stages: string[];
}

export interface WorkerHealth {
  /** The most-recently-seen worker, or null if none has ever reported. */
  freshest: WorkerRow | null;
  /** Seconds since the freshest worker was seen (Infinity if none). */
  ageSeconds: number;
  /** True when no worker has reported within the staleness window. */
  stale: boolean;
  /** Providers any *currently-alive* worker can service (for Start pre-flight). */
  liveProviders: string[];
  loading: boolean;
}

const POLL_MS = 5000;
// A healthy worker refreshes every loop pass (~2s idle); 30s of silence means
// it's down/stuck — this is the signal the run-#7 black hole lacked.
const STALE_AFTER_S = 30;

function ageSecondsOf(iso: string): number {
  return Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
}

// Reads worker_status for the /ops health signal: is any worker alive, how long
// ago was it seen, and which providers can it service right now.
export function useWorkerHealth(): WorkerHealth {
  const query = useQuery({
    queryKey: ['worker_status'],
    queryFn: async () => {
      const { data, error } = await supabase
        .from('worker_status')
        .select('worker_id, last_seen, providers, stages')
        .order('last_seen', { ascending: false });
      if (error) throw error;
      return (data ?? []) as WorkerRow[];
    },
    refetchInterval: POLL_MS,
  });

  const rows = query.data ?? [];
  const freshest = rows[0] ?? null;
  const ageSeconds = freshest ? ageSecondsOf(freshest.last_seen) : Infinity;
  const stale = ageSeconds > STALE_AFTER_S;
  const liveProviders = Array.from(
    new Set(
      rows
        .filter((r) => ageSecondsOf(r.last_seen) <= STALE_AFTER_S)
        .flatMap((r) => r.providers ?? []),
    ),
  );

  return { freshest, ageSeconds, stale, liveProviders, loading: query.isPending };
}
