import { useQuery } from '@tanstack/react-query';
import { queryTable } from '../api';
import type { StageReview } from '../components/reviews/ReviewCard';

// Full open human_reviews rows — the actionable queue (human flags + machine
// proposals) an admin can resolve or dismiss. Distinct from `needs_review`,
// which also surfaces non-actionable pipeline gaps (abstains) that have no
// human_reviews row.
export async function fetchOpenReviews(
  page = 1,
  pageSize = 50,
): Promise<{ rows: StageReview[]; total: number }> {
  return queryTable<StageReview>({
    table: 'human_reviews',
    select: 'id, entity_kind, entity_id, stage, state, origin, payload, note',
    filters: [{ col: 'state', op: 'eq', value: 'open' }],
    order: { col: 'created_at', asc: true },
    limit: pageSize,
    offset: (page - 1) * pageSize,
  });
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
