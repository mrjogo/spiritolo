import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { supabase } from '../../supabase';
import { useRpc } from '../hooks/useRpc';
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
  last_run_label?: string;
  total_count?: number;
}

export interface UseEligiblePoolResult {
  rows: EligibleRow[];
  total: number;
  facets: Facets;
  status: 'loading' | 'error' | 'loaded';
  pending: boolean;
}

function readTotal(rows: EligibleRow[]): number {
  if (rows.length === 0) return 0;
  const stamped = rows[0].total_count;
  return typeof stamped === 'number' ? stamped : rows.length;
}

// Reads a page of the eligible pool via eligible_pool + eligible_pool_facets.
// keepPreviousData holds the prior page on screen while a filter change loads,
// so the JIRA-style facet counts don't flash empty.
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
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const { data, error } = await supabase.rpc('eligible_pool', {
        stage,
        p_filter: pFilter,
        sort: serializeSort(sort),
        limit: pageSize,
        offset,
      });
      if (error) throw error;
      return (data as EligibleRow[] | null) ?? [];
    },
  });

  const facetsQuery = useQuery({
    queryKey: ['eligiblePoolFacets', stage, pFilter],
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const { data, error } = await supabase.rpc('eligible_pool_facets', {
        stage,
        p_filter: pFilter,
      });
      if (error) throw error;
      return (data as Facets | null) ?? {};
    },
  });

  const rows = poolQuery.data ?? [];
  return {
    rows,
    total: readTotal(rows),
    facets: facetsQuery.data ?? {},
    status: poolQuery.isError ? 'error' : poolQuery.isPending ? 'loading' : 'loaded',
    pending: poolQuery.isFetching && !poolQuery.isPending,
  };
}

// --- Add-to-run mutations -------------------------------------------------

type AddByIdsArgs = { job_id: number; entity_type: string; entity_ids: string[] };
type AddByFilterArgs = { job_id: number; p_filter: PFilter };

/** add_run_items(job_id, entity_type, entity_ids[]) — the explicit selection. */
export function useAddRunItems(jobId: number) {
  return useRpc<AddByIdsArgs, number>('add_run_items', {
    invalidate: [['run', jobId], ['runItems'], ['runItemsFacets']],
  });
}

/** add_run_items_by_filter(job_id, p_filter) — the "all N matching" path,
 *  where the server re-derives the set from the filter. */
export function useAddRunItemsByFilter(jobId: number) {
  return useRpc<AddByFilterArgs, number>('add_run_items_by_filter', {
    invalidate: [['run', jobId], ['runItems'], ['runItemsFacets']],
  });
}
