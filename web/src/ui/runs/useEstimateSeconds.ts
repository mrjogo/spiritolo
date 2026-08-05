import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../supabase';

// Live rough time estimate for a run: seconds-per-item (from history, else a
// seed) × item count, returned as { seconds, source }. Mirrors
// useEstimatedRunCents — the pricing and timing math both live server-side, so
// the preview an operator sees comes from one source and never drifts. `source`
// (model|provider|stage|seed) lets the UI hedge a low-confidence (seed) estimate.
export function useEstimatedRunSeconds(
  stage: string | null | undefined,
  provider: string | null | undefined,
  model: string | null | undefined,
  items: number | null | undefined,
  enabled: boolean,
): { seconds: number; source: string } | null {
  const q = useQuery({
    queryKey: ['estimateRunSeconds', stage, provider, model, items],
    enabled:
      enabled && stage != null && provider != null && model != null && items != null,
    queryFn: async () => {
      const { data, error } = await supabase.rpc('estimate_run_seconds', {
        p_stage: stage,
        p_provider: provider,
        p_model: model,
        p_items: items,
      });
      if (error) throw error;
      return data as { seconds: number; source: string };
    },
  });
  return q.data ?? null;
}
