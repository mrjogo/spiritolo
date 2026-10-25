import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { api, type Page } from '../../api';
import { useApiMutation } from '../hooks/useApiMutation';
import type { PFilter } from './filter';
import { serializeSort, type Facets, type Sort } from './useRunItems';

// One row of the eligible pool an operator browses on the Add-tasks page —
// every entity that qualifies for the stage, with its current map/parse/etc.
// status and last-run marker.
export interface EligibleRow {
  entity_id: string;
  title: string;
  source: string;
  /** e.g. "flagged", "failed", "never_run" — feeds the status badge. */
  status: string;
  /** Optional richer status detail, e.g. "flagged · 2 names". */
  status_detail?: string;
  last_run_label?: string | null;
}

export interface UseEligiblePoolResult {
  rows: EligibleRow[];
  total: number;
  facets: Facets;
  status: 'loading' | 'error' | 'loaded';
  pending: boolean;
}

// Reads a page of the eligible pool (POST /api/ops/eligible-pool) + its facets.
// keepPreviousData holds the prior page on screen while a filter change loads,
// so the JIRA-style facet counts don't flash empty. Both stay idle until the
// stage is known (the run header loads first): querying with an empty stage
// would return the wrong universe and leave its counts on screen.
export function useEligiblePool(
  stage: string,
  pFilter: PFilter,
  sort: Sort[],
  page: number,
  pageSize: number,
): UseEligiblePoolResult {
  const offset = (page - 1) * pageSize;

  const poolQuery = useQuery({
    queryKey: ['eligiblePool', stage, pFilter, sort, page, pageSize],
    enabled: stage !== '',
    placeholderData: keepPreviousData,
    queryFn: () =>
      api<Page<EligibleRow>>('/api/ops/eligible-pool', {
        body: { stage, filter: pFilter, sort: serializeSort(sort), limit: pageSize, offset },
      }),
  });

  const facetsQuery = useQuery({
    queryKey: ['eligiblePoolFacets', stage, pFilter],
    enabled: stage !== '',
    placeholderData: keepPreviousData,
    queryFn: () => api<Facets>('/api/ops/eligible-pool/facets', { body: { stage, filter: pFilter } }),
  });

  return {
    rows: poolQuery.data?.rows ?? [],
    total: poolQuery.data?.total ?? 0,
    facets: facetsQuery.data ?? {},
    status: poolQuery.isError ? 'error' : poolQuery.isPending ? 'loading' : 'loaded',
    pending: poolQuery.isFetching && !poolQuery.isPending,
  };
}

// --- Add-to-run mutations -------------------------------------------------

type AddByIdsArgs = { job_id: number; entity_type: string; entity_ids: string[] };
type AddByFilterArgs = { job_id: number; p_filter: PFilter };

/** POST /api/ops/runs/:id/items {entity_type, entity_ids} — the explicit selection. */
export function useAddRunItems(jobId: number) {
  return useApiMutation<AddByIdsArgs, number>(
    async (a) => (await api<{ added: number }>(`/api/ops/runs/${a.job_id}/items`, {
      body: { entity_type: a.entity_type, entity_ids: a.entity_ids },
    })).added,
    { invalidate: [['run', jobId], ['runItems'], ['runItemsFacets']] },
  );
}

/** POST /api/ops/runs/:id/items {filter} — the "all N matching" path, where
 *  the server re-derives the set from the filter. */
export function useAddRunItemsByFilter(jobId: number) {
  return useApiMutation<AddByFilterArgs, number>(
    async (a) => (await api<{ added: number }>(`/api/ops/runs/${a.job_id}/items`, {
      body: { filter: a.p_filter },
    })).added,
    { invalidate: [['run', jobId], ['runItems'], ['runItemsFacets']] },
  );
}
