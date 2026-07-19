import { useQuery } from '@tanstack/react-query';
import { supabase } from '../supabase';
import type { StageReview } from '../components/reviews/ReviewCard';

// Full open human_reviews rows — the actionable queue (human flags + machine
// proposals) an admin can resolve or dismiss. Distinct from `needs_review`,
// which also surfaces non-actionable pipeline gaps (abstains) that have no
// human_reviews row. Admin-only read is enforced by the table's RLS policy.
export async function fetchOpenReviews(
  page = 1,
  pageSize = 50,
): Promise<{ rows: StageReview[]; total: number }> {
  const from = (page - 1) * pageSize;
  const to = from + pageSize - 1;
  const { data, count, error } = await supabase
    .from('human_reviews')
    .select('id, entity_kind, entity_id, stage, state, origin, payload, note', {
      count: 'exact',
    })
    .eq('state', 'open')
    .order('created_at', { ascending: true })
    .range(from, to);
  if (error) throw error;
  return { rows: (data ?? []) as StageReview[], total: count ?? 0 };
}

// Prefix key: invalidating ['openReviews'] refreshes every page.
export const openReviewsQueryKey = ['openReviews'] as const;

export function useOpenReviews(
  page = 1,
  pageSize = 50,
): { rows: StageReview[]; total: number; status: string } {
  const query = useQuery({
    queryKey: [...openReviewsQueryKey, page, pageSize],
    queryFn: () => fetchOpenReviews(page, pageSize),
  });
  return {
    rows: query.data?.rows ?? [],
    total: query.data?.total ?? 0,
    status: query.isError ? 'error' : query.isPending ? 'loading' : 'loaded',
  };
}
