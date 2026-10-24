import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { queryTable, type QueryFilter, type FilterOp } from '../../api';

// Kept under their old names: the ops browsers and FilterBar build filters
// with this type, and the semantics (col/op/value, applied in order) are the
// same — only the transport changed from PostgREST to POST /api/ops/query.
export type PostgrestFilterOp = FilterOp;
export type PostgrestFilter = QueryFilter;

export interface UsePagedQueryOpts {
  table: string;
  select: string;
  filters?: PostgrestFilter[];
  order?: { col: string; asc?: boolean };
  page: number;
  pageSize: number;
}

export interface UsePagedQueryResult<T> {
  rows: T[];
  total: number;
  status: 'loading' | 'error' | 'loaded';
  pending: boolean;
}

// One paged read of an allowlisted table/view. placeholderData keeps the prior
// page's rows on screen (pending=true) instead of flashing to a loading state.
export function usePagedQuery<T>(opts: UsePagedQueryOpts): UsePagedQueryResult<T> {
  const { table, select, filters = [], order, page, pageSize } = opts;
  const offset = (page - 1) * pageSize;

  const query = useQuery({
    queryKey: ['pagedQuery', table, select, filters, order, page, pageSize],
    queryFn: () => queryTable<T>({ table, select, filters, order, limit: pageSize, offset }),
    placeholderData: keepPreviousData,
  });

  return {
    rows: query.data?.rows ?? [],
    total: query.data?.total ?? 0,
    status: query.isError ? 'error' : query.isPending ? 'loading' : 'loaded',
    pending: query.isFetching && !query.isPending,
  };
}
