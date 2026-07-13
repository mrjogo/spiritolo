import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../supabase';

export interface StageQueueCountRow {
  stage: string;
  queue_depth: number;
}

async function fetchStageQueueCounts(): Promise<StageQueueCountRow[]> {
  const { data, error } = await supabase.rpc('stage_queue_counts');
  if (error) throw error;
  return (data ?? []) as StageQueueCountRow[];
}

export interface UseStageQueueCountsResult {
  rows: StageQueueCountRow[];
  status: 'loading' | 'error' | 'loaded';
}

// One RPC call serves every StageCard: react-query dedupes identical
// concurrent callers under this queryKey, so mounting nine cards issues a
// single network request. A stage with no row (discover/classify/fetch,
// still SQLite-backed; role, folded into cluster) is "not tracked", not
// zero — queueDepthForStage keeps that distinction for callers.
export function useStageQueueCounts(): UseStageQueueCountsResult {
  const query = useQuery({
    queryKey: ['stageQueueCounts'],
    queryFn: fetchStageQueueCounts,
  });
  return {
    rows: query.data ?? [],
    status: query.isError ? 'error' : query.isPending ? 'loading' : 'loaded',
  };
}

export function queueDepthForStage(rows: StageQueueCountRow[], stage: string): number | null {
  const row = rows.find((r) => r.stage === stage);
  return row ? row.queue_depth : null;
}
