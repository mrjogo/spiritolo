import { useQuery } from '@tanstack/react-query';
import { supabase } from '../supabase';
import type { StageReview } from '../components/reviews/ReviewCard';

// Full open stage_reviews rows — the actionable queue (human flags + machine
// proposals) an admin can resolve or dismiss. Distinct from `needs_review`,
// which also surfaces non-actionable pipeline gaps (abstains) that have no
// stage_reviews row. Admin-only read is enforced by the table's RLS policy.
export async function fetchOpenReviews(): Promise<StageReview[]> {
  const { data, error } = await supabase
    .from('stage_reviews')
    .select('id, entity_kind, entity_id, stage, state, origin, payload, note')
    .eq('state', 'open')
    .order('created_at', { ascending: true });
  if (error) throw error;
  return (data ?? []) as StageReview[];
}

export const openReviewsQueryKey = ['openReviews'] as const;

export function useOpenReviews(): { rows: StageReview[]; status: string } {
  const query = useQuery({
    queryKey: openReviewsQueryKey,
    queryFn: fetchOpenReviews,
  });
  return {
    rows: query.data ?? [],
    status: query.isError ? 'error' : query.isPending ? 'loading' : 'loaded',
  };
}
