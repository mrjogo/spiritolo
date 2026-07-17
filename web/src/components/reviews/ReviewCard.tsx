import type { ComponentType } from 'react';
import { resolveReview, dismissReview } from '../../reviews/flagReview';
import { MapReviewBody } from './bodies/MapReviewBody';
import { ParseReviewBody } from './bodies/ParseReviewBody';

// Mirrors a `stage_reviews` row (the committed DB surface). Owned here because
// the card and its per-stage bodies all key off this shape.
export interface StageReview {
  id: number;
  entity_kind: string;
  entity_id: string;
  stage: string;
  state: 'open' | 'resolved' | 'dismissed';
  origin: 'human_flag' | 'machine_proposal' | 'distance_gate';
  payload: unknown | null;
  note: string | null;
}

// Per-stage review bodies, keyed by `stage_reviews.stage`. A stage without a
// registered body falls back to a raw payload dump.
const BODIES: Record<string, ComponentType<{ review: StageReview }>> = {
  map: MapReviewBody,
  parse: ParseReviewBody,
};

// Shared review shell: origin + note + a stage-specific body, with Resolve
// (attaches the payload as the fix) and Dismiss (no fix) actions wired to the
// review RPC clients.
export function ReviewCard({ review }: { review: StageReview }) {
  const Body = BODIES[review.stage];

  return (
    <div
      className="review-card"
      style={{
        border: '1px solid var(--ops-border, #e3e5e9)',
        borderRadius: 6,
        padding: 12,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12 }}>
        <span
          className="review-card__origin"
          style={{ fontFamily: 'monospace', opacity: 0.8 }}
        >
          {review.origin}
        </span>
        <span className="review-card__stage" style={{ opacity: 0.6 }}>
          {review.stage}
        </span>
      </div>

      {review.note && (
        <p className="review-card__note" style={{ margin: 0 }}>
          {review.note}
        </p>
      )}

      <div className="review-card__body">
        {Body ? (
          <Body review={review} />
        ) : (
          <pre
            data-testid="review-payload-fallback"
            style={{ margin: 0, fontSize: 12, overflowX: 'auto' }}
          >
            {JSON.stringify(review.payload, null, 2)}
          </pre>
        )}
      </div>

      <div className="review-card__actions" style={{ display: 'flex', gap: 8 }}>
        <button
          type="button"
          onClick={() => void resolveReview({ id: review.id, payload: review.payload })}
        >
          Resolve
        </button>
        <button type="button" onClick={() => void dismissReview(review.id)}>
          Dismiss
        </button>
      </div>
    </div>
  );
}
