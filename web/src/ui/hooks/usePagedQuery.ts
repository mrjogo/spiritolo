import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { supabase } from '../../supabase';

export type PostgrestFilterOp = 'eq' | 'in' | 'lt' | 'lte' | 'gt' | 'gte' | 'neq' | 'ilike';

export interface PostgrestFilter {
  col: string;
  op: PostgrestFilterOp;
  value: unknown;
}

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

// The DRY replacement for the hand-rolled useEffect fetch in
// RecipeList/RecipeDetail — builds the PostgREST select/filter/order/range
// chain and, via placeholderData: keepPreviousData, keeps the prior page's
// rows on screen (pending=true) instead of flashing to a loading state.
export function usePagedQuery<T>(opts: UsePagedQueryOpts): UsePagedQueryResult<T> {
  const { table, select, filters = [], order, page, pageSize } = opts;
  const from = (page - 1) * pageSize;
  const to = from + pageSize - 1;

  const query = useQuery({
    queryKey: ['pagedQuery', table, select, filters, order, page, pageSize],
    queryFn: async () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let q: any = supabase.from(table).select(select, { count: 'exact' });
      for (const f of filters) {
        q = q[f.op](f.col, f.value);
      }
      if (order) q = q.order(order.col, { ascending: order.asc ?? true });
      const { data, count, error } = await q.range(from, to);
      if (error) throw error;
      return { rows: (data ?? []) as T[], total: count ?? 0 };
    },
    placeholderData: keepPreviousData,
  });

  return {
    rows: query.data?.rows ?? [],
    total: query.data?.total ?? 0,
    status: query.isError ? 'error' : query.isPending ? 'loading' : 'loaded',
    pending: query.isFetching && !query.isPending,
  };
}
