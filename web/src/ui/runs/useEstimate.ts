import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../supabase';

// Live cost estimate for a DRAFT run. Calls the estimate_run_cents RPC — the
// same server-side `_estimate_cents` helper start_run stamps onto
// cost_estimate_cents — so the preview the operator sees and the amount the run
// is actually gated on come from one source and never drift. Once a run is
// started, read the stamped `cost_estimate_cents` directly instead of this.
export function useEstimatedRunCents(
  provider: string | null | undefined,
  model: string | null | undefined,
  items: number | null | undefined,
  enabled: boolean,
): number | null {
  const q = useQuery({
    queryKey: ['estimateRunCents', provider, model, items],
    enabled: enabled && provider != null && model != null && items != null,
    queryFn: async () => {
      const { data, error } = await supabase.rpc('estimate_run_cents', {
        provider,
        model,
        items,
      });
      if (error) throw error;
      return (data as number | null) ?? 0;
    },
  });
  return q.data ?? null;
}
