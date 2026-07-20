import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../supabase';
import { useRpc } from '../hooks/useRpc';
import type { PFilter } from './filter';

// The per-entity task state within a run (the latest job_item outcome).
export type TaskStatus =
  | 'pending'
  | 'running'
  | 'applied'
  | 'flagged'
  | 'failed';

// Why an entity was pulled into the run — the "why added" column. Mirrors the
// eligible-pool status that qualified it.
export type WhyAdded = 'flagged' | 'never_run' | 'retry_failed' | 'applied';

// One row of the run's task list (run_items RPC).
export interface RunItem {
  item_id: string;
  entity_id: string;
  title: string;
  source: string;
  why_added: WhyAdded;
  task_state: TaskStatus;
  /** Window count the RPC stamps on every row so the pager knows the total
   *  without a second round-trip. */
  total_count?: number;
}

// Facet counts keyed by dimension → value → count (eligible_pool_facets /
// run_items_facets shape: { status: { flagged: N, ... }, source: { ... } }).
export type Facets = Record<string, Record<string, number>>;

export interface Sort {
  col: string;
  asc: boolean;
}

export interface UseRunItemsResult {
  rows: RunItem[];
  total: number;
  facets: Facets;
  status: 'loading' | 'error' | 'loaded';
}

function readTotal(rows: RunItem[]): number {
  if (rows.length === 0) return 0;
  const stamped = rows[0].total_count;
  return typeof stamped === 'number' ? stamped : rows.length;
}

// Reads a page of a run's tasks via run_items + run_items_facets. The
// p_filter is the same jsonb the RPCs share with the eligible pool, so the
// in-run status chips and the add-tasks filters speak one language.
export function useRunItems(
  jobId: number | null,
  pFilter: PFilter,
  sort: Sort,
  page: number,
  pageSize: number,
): UseRunItemsResult {
  const offset = (page - 1) * pageSize;

  const itemsQuery = useQuery({
    queryKey: ['runItems', jobId, pFilter, sort, page, pageSize],
    enabled: jobId != null,
    queryFn: async () => {
      const { data, error } = await supabase.rpc('run_items', {
        job_id: jobId,
        p_filter: pFilter,
        sort: `${sort.col}:${sort.asc ? 'asc' : 'desc'}`,
        limit: pageSize,
        offset,
      });
      if (error) throw error;
      return (data as RunItem[] | null) ?? [];
    },
  });

  const facetsQuery = useQuery({
    queryKey: ['runItemsFacets', jobId, pFilter],
    enabled: jobId != null,
    queryFn: async () => {
      const { data, error } = await supabase.rpc('run_items_facets', {
        job_id: jobId,
        p_filter: pFilter,
      });
      if (error) throw error;
      return (data as Facets | null) ?? {};
    },
  });

  const rows = itemsQuery.data ?? [];
  return {
    rows,
    total: readTotal(rows),
    facets: facetsQuery.data ?? {},
    status: itemsQuery.isError ? 'error' : itemsQuery.isPending ? 'loading' : 'loaded',
  };
}

// --- Item-level mutations -------------------------------------------------

type RemoveArgs = { job_id: number; item_ids: string[] };

/** remove_run_items(job_id, item_ids[]) — draft-run only. */
export function useRemoveRunItems(jobId: number) {
  return useRpc<RemoveArgs, void>('remove_run_items', {
    invalidate: [['runItems'], ['runItemsFacets'], ['run', jobId]],
  });
}
