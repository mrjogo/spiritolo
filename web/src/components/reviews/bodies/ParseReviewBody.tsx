import type { StageReview } from '../ReviewCard';

// Read-only body for a `parse-ingredients`-stage review: shows the ingredient fields the
// parser produced (name + amount + unit). Payload is untyped jsonb off the
// human_reviews row, so each field is narrowed defensively.
interface ParsePayload {
  name?: unknown;
  amount?: unknown;
  unit?: unknown;
}

function displayValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'string') return v;
  if (typeof v === 'number') return String(v);
  return JSON.stringify(v);
}

export function ParseReviewBody({ review }: { review: StageReview }) {
  const payload = (review.payload ?? {}) as ParsePayload;

  return (
    <dl
      className="review-body review-body--parse"
      data-testid="parse-review-body"
      style={{ margin: 0, display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '2px 12px' }}
    >
      <dt style={{ fontSize: 11, opacity: 0.7 }}>name</dt>
      <dd style={{ margin: 0 }}>{displayValue(payload.name)}</dd>
      <dt style={{ fontSize: 11, opacity: 0.7 }}>amount</dt>
      <dd style={{ margin: 0 }}>{displayValue(payload.amount)}</dd>
      <dt style={{ fontSize: 11, opacity: 0.7 }}>unit</dt>
      <dd style={{ margin: 0 }}>{displayValue(payload.unit)}</dd>
    </dl>
  );
}
