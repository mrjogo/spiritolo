import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';

// Live cost estimate for a DRAFT run. GET /api/ops/estimate runs the same
// server-side estimate start_run stamps onto cost_estimate_cents, so the
// preview the operator sees and the amount the run is gated on come from one
// source and never drift. Once a run is started, read the stamped
// `cost_estimate_cents` directly instead of this.
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
      const params = new URLSearchParams({ provider: provider ?? '', model: model ?? '', items: String(items ?? 0) });
      return (await api<{ cents: number }>(`/api/ops/estimate?${params}`)).cents;
    },
  });
  return q.data ?? null;
}
