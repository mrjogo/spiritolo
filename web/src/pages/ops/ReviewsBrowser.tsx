import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useNeedsReview } from '../../reviews/useNeedsReview';
import { useOpenReviews, openReviewsQueryKey } from '../../reviews/useOpenReviews';
import { ReviewCard } from '../../components/reviews/ReviewCard';
import type { StageReview } from '../../components/reviews/ReviewCard';
import { Pager } from '../../ui/Pager';

const PAGE_SIZE = 50;
const STUCK_CAP = 100;

// needs_review reasons that are NOT an actionable human_reviews row — the
// pipeline couldn't finish (no human/machine review to resolve yet).
const STUCK_REASONS = new Set(['abstain', 'proposes_new', 'low_confidence']);

// A small free-text pill for a needs_review `reason`.
function ReasonPill({ reason }: { reason: string }) {
  return (
    <span
      style={{
        fontSize: 11,
        padding: '1px 8px',
        borderRadius: 999,
        border: '1px solid var(--ops-border, #e3e5e9)',
        opacity: 0.85,
        whiteSpace: 'nowrap',
      }}
    >
      {reason}
    </span>
  );
}

function groupByStage<T extends { stage: string }>(rows: T[]): Map<string, T[]> {
  const byStage = new Map<string, T[]>();
  for (const row of rows) {
    const list = byStage.get(row.stage);
    if (list) list.push(row);
    else byStage.set(row.stage, [row]);
  }
  return byStage;
}

// The reviews console: actionable open reviews (resolve/dismiss) on top, then a
// read-only "pipeline stuck" list of needs_review gaps that aren't yet a review.
export function ReviewsBrowser() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const { rows: reviews, total, status: reviewsStatus } = useOpenReviews(page, PAGE_SIZE);
  const { rows: needs } = useNeedsReview();

  const refetch = () => {
    void queryClient.invalidateQueries({ queryKey: openReviewsQueryKey });
    void queryClient.invalidateQueries({ queryKey: ['needsReview'] });
  };

  const reviewsByStage = groupByStage<StageReview>(reviews);
  const allStuck = needs.filter((r) => STUCK_REASONS.has(r.reason));
  const stuck = allStuck.slice(0, STUCK_CAP);
  const stuckByStage = groupByStage(stuck);

  return (
    <div className="ops-reviews">
      <h2 style={{ fontSize: 16, margin: '0 0 8px' }}>Reviews</h2>
      {reviewsStatus === 'loading' ? (
        <p style={{ fontSize: 12, opacity: 0.7 }}>Loading…</p>
      ) : (
        <Pager page={page} pageSize={PAGE_SIZE} total={total} onPage={setPage} unit="open reviews" />
      )}

      {reviewsStatus !== 'loading' && reviews.length === 0 && (
        <p style={{ fontStyle: 'italic', opacity: 0.7 }}>No open reviews.</p>
      )}

      {[...reviewsByStage.entries()].map(([stage, stageReviews]) => (
        <section key={stage} aria-label={`${stage} reviews`} style={{ marginBottom: 16 }}>
          <h3 style={{ margin: '0 0 8px', fontSize: 14 }}>
            {stage}{' '}
            <span style={{ opacity: 0.6, fontWeight: 400 }}>({stageReviews.length})</span>
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {stageReviews.map((review) => (
              <ReviewCard key={review.id} review={review} onActed={refetch} />
            ))}
          </div>
        </section>
      ))}

      {stuck.length > 0 && (
        <section aria-label="pipeline stuck" style={{ marginTop: 24 }}>
          <h3 style={{ margin: '0 0 4px', fontSize: 14 }}>Pipeline stuck</h3>
          <p style={{ fontSize: 12, opacity: 0.6, margin: '0 0 8px' }}>
            The pipeline couldn&rsquo;t finish these — not yet an actionable review.
            {allStuck.length > STUCK_CAP && ` (showing first ${STUCK_CAP} of ${allStuck.length})`}
          </p>
          {[...stuckByStage.entries()].map(([stage, stageRows]) => (
            <section key={stage} aria-label={`${stage} stuck`} style={{ marginBottom: 12 }}>
              <h4 style={{ margin: '0 0 6px', fontSize: 13, fontWeight: 500 }}>
                {stage} <span style={{ opacity: 0.6 }}>({stageRows.length})</span>
              </h4>
              <ul
                role="list"
                style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 6 }}
              >
                {stageRows.map((row, i) => (
                  <li
                    key={`${row.entity_kind}:${row.entity_id}:${row.stage}:${i}`}
                    style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, padding: '4px 0', borderTop: '1px solid var(--ops-border, #eef0f3)' }}
                  >
                    <span style={{ opacity: 0.7 }}>{row.entity_kind}</span>
                    <span style={{ fontFamily: 'monospace' }}>{row.entity_id}</span>
                    <ReasonPill reason={row.reason} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </section>
      )}
    </div>
  );
}
