import { useQuery } from '@tanstack/react-query';
import { api, type Page } from '../../api';
import { useApiMutation } from '../hooks/useApiMutation';
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

// One row of the run's task list (POST /api/ops/runs/:id/items/query).
export interface RunItem {
  item_id: string;
  entity_id: string;
  title: string;
  source: string;
  why_added: WhyAdded;
  task_state: TaskStatus;
}

// Facet counts keyed by dimension → value → count (the facets endpoints'
// shape: { status: { flagged: N, ... }, source: { ... } }).
export type Facets = Record<string, Record<string, number>>;

// One sort key. An ordered list of these is a multidimensional sort: the first
// key is primary, each subsequent key breaks ties within the previous.
export interface Sort {
  col: string;
  asc: boolean;
}

/** Serialize an ordered sort to the API's comma-separated "col:dir" form. */
export function serializeSort(keys: Sort[]): string {
  return keys.map((k) => `${k.col}:${k.asc ? 'asc' : 'desc'}`).join(',');
}

export interface UseRunItemsResult {
  rows: RunItem[];
  total: number;
  facets: Facets;
  status: 'loading' | 'error' | 'loaded';
}

// Reads a page of a run's tasks plus its facet counts. The filter is the same
// object the eligible pool takes, so the in-run status chips and the
// add-tasks filters speak one language.
export function useRunItems(
  jobId: number | null,
  pFilter: PFilter,
  sort: Sort[],
  page: number,
  pageSize: number,
): UseRunItemsResult {
  const offset = (page - 1) * pageSize;

  const itemsQuery = useQuery({
    queryKey: ['runItems', jobId, pFilter, sort, page, pageSize],
    enabled: jobId != null,
    queryFn: () =>
      api<Page<RunItem>>(`/api/ops/runs/${jobId}/items/query`, {
        body: { filter: pFilter, sort: serializeSort(sort), limit: pageSize, offset },
      }),
  });

  const facetsQuery = useQuery({
    queryKey: ['runItemsFacets', jobId, pFilter],
    enabled: jobId != null,
    queryFn: () => api<Facets>(`/api/ops/runs/${jobId}/items/facets`, { body: { filter: pFilter } }),
  });

  return {
    rows: itemsQuery.data?.rows ?? [],
    total: itemsQuery.data?.total ?? 0,
    facets: facetsQuery.data ?? {},
    status: itemsQuery.isError ? 'error' : itemsQuery.isPending ? 'loading' : 'loaded',
  };
}

// --- Item-level mutations -------------------------------------------------

type RemoveArgs = { job_id: number; item_ids: string[] };

/** POST /api/ops/runs/:id/items/remove {item_ids} — draft-run only. */
export function useRemoveRunItems(jobId: number) {
  return useApiMutation<RemoveArgs, void>(
    async (a) => { await api(`/api/ops/runs/${a.job_id}/items/remove`, { body: { item_ids: a.item_ids } }); },
    { invalidate: [['runItems'], ['runItemsFacets'], ['run', jobId]] },
  );
}
