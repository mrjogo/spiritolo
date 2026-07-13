import { useQuery } from '@tanstack/react-query';
import { supabase } from '../supabase';
import { PIPELINE_STAGES, type PipelineStage } from './pipelineStages';

export { PIPELINE_STAGES, type PipelineStage };

export interface StageConfigRow {
  stage: string;
  metered: boolean;
  requires_approval: boolean;
}

// Pure lookups over an already-fetched config, so callers (and tests) never
// hardcode which stages are metered — that fact lives in the stage_config
// table the owner rewires, not in this code. A stage missing from the config
// defaults to free/no-approval rather than throwing.
export function isMetered(rows: StageConfigRow[], stage: string): boolean {
  return rows.find((r) => r.stage === stage)?.metered ?? false;
}

export function requiresApproval(rows: StageConfigRow[], stage: string): boolean {
  return rows.find((r) => r.stage === stage)?.requires_approval ?? false;
}

async function fetchStageConfig(): Promise<StageConfigRow[]> {
  const { data, error } = await supabase
    .from('stage_config')
    .select('stage, metered, requires_approval');
  if (error) throw error;
  return (data ?? []) as StageConfigRow[];
}

// stage_config rarely changes (an operator edits it deliberately when
// rewiring a provider chain), so it's cached indefinitely rather than
// refetched on every mount/focus.
export function useStageConfig(): { rows: StageConfigRow[]; isLoading: boolean } {
  const query = useQuery({
    queryKey: ['stageConfig'],
    queryFn: fetchStageConfig,
    staleTime: Infinity,
  });
  return { rows: query.data ?? [], isLoading: query.isPending };
}
