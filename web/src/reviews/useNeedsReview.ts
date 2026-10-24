import { useQuery } from '@tanstack/react-query';
import { queryAll } from '../api';

// One row per open item surfaced by the `needs_review` view — the union of
// human flags, machine proposals, and distance-gate misses across every stage.
export interface NeedsReviewRow {
  entity_kind: string;
  entity_id: string;
  stage: string;
  reason: string;
}

function fetchNeedsReview(): Promise<NeedsReviewRow[]> {
  return queryAll<NeedsReviewRow>('needs_review');
}

// react-query hook: identical concurrent callers dedupe under this queryKey,
// so multiple consumers issue a single fetch.
export function useNeedsReview(): { rows: NeedsReviewRow[]; status: string } {
  const query = useQuery({
    queryKey: ['needsReview'],
    queryFn: fetchNeedsReview,
  });
  return {
    rows: query.data ?? [],
    status: query.isError ? 'error' : query.isPending ? 'loading' : 'loaded',
  };
}
