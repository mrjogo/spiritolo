import type { StageReview } from '../ReviewCard';

// Read-only body for a `map-ingredient`-stage review: shows the slug the mapper proposed
// and the ranked candidates it considered. Payload is untyped jsonb off the
// human_reviews row, so every field is narrowed defensively.
interface MapPayload {
  proposed_slug?: unknown;
  candidates?: unknown;
}

function candidateLabel(c: unknown): string {
  if (typeof c === 'string') return c;
  if (c && typeof c === 'object') {
    const obj = c as Record<string, unknown>;
    const slug = typeof obj.slug === 'string' ? obj.slug : null;
    const score = typeof obj.score === 'number' ? obj.score : null;
    if (slug && score !== null) return `${slug} (${score.toFixed(2)})`;
    if (slug) return slug;
  }
  return JSON.stringify(c);
}

export function MapReviewBody({ review }: { review: StageReview }) {
  const payload = (review.payload ?? {}) as MapPayload;
  const proposedSlug =
    typeof payload.proposed_slug === 'string' ? payload.proposed_slug : null;
  const candidates = Array.isArray(payload.candidates) ? payload.candidates : [];

  return (
    <div className="review-body review-body--map" data-testid="map-review-body">
      <dl style={{ margin: 0 }}>
        <dt style={{ fontSize: 11, opacity: 0.7 }}>proposed slug</dt>
        <dd style={{ margin: '0 0 8px', fontFamily: 'monospace' }}>
          {proposedSlug ?? '—'}
        </dd>
      </dl>
      <div>
        <div style={{ fontSize: 11, opacity: 0.7 }}>candidates</div>
        {candidates.length === 0 ? (
          <span>—</span>
        ) : (
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
            {candidates.map((c, i) => (
              <li key={i} style={{ fontFamily: 'monospace', fontSize: 13 }}>
                {candidateLabel(c)}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
