import { useQuery } from '@tanstack/react-query';
import { supabase } from '../supabase';

// One row per open item surfaced by the committed `needs_review` view — the
// union of human flags, machine proposals, and distance-gate misses across
// every stage. Shape matches the view's columns exactly.
export interface NeedsReviewRow {
  entity_kind: string;
  entity_id: string;
  stage: string;
  reason: string;
}

async function fetchNeedsReview(): Promise<NeedsReviewRow[]> {
  const { data, error } = await supabase.from('needs_review').select('*');
  if (error) throw error;
  return (data ?? []) as NeedsReviewRow[];
}

// react-query hook mirroring useStageQueueCounts: identical concurrent callers
// dedupe under this queryKey, so multiple consumers issue a single fetch.
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
