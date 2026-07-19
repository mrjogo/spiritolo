import type { StageReview } from '../ReviewCard';

// Read-only body for a `combine-nodes`-stage review: a machine proposal to
// merge/keep a provisional node. Shows the candidate nodes the combiner
// considered (slug, display name, live/provisional status). Payload is untyped
// jsonb off the human_reviews row, so every field is narrowed defensively.
//
// Resolving means writing a payload picking a survivor for the absorbed node
// (this review's entity_id) — see the hint line below.
interface CombineCandidate {
  slug: string | null;
  display_name: string | null;
  status: string | null;
}

interface CombinePayload {
  candidates?: unknown;
}

function narrowCandidate(c: unknown): CombineCandidate {
  if (c && typeof c === 'object') {
    const obj = c as Record<string, unknown>;
    return {
      slug: typeof obj.slug === 'string' ? obj.slug : null,
      display_name: typeof obj.display_name === 'string' ? obj.display_name : null,
      status: typeof obj.status === 'string' ? obj.status : null,
    };
  }
  return { slug: null, display_name: null, status: null };
}

function StatusChip({ status }: { status: string | null }) {
  if (!status) return null;
  const provisional = status === 'provisional';
  return (
    <span
      style={{
        fontSize: 10,
        textTransform: 'uppercase',
        letterSpacing: '0.03em',
        padding: '1px 6px',
        borderRadius: 8,
        border: '1px solid var(--ops-border, #e3e5e9)',
        opacity: provisional ? 0.7 : 1,
        fontWeight: provisional ? 400 : 600,
      }}
    >
      {status}
    </span>
  );
}

export function CombineReviewBody({ review }: { review: StageReview }) {
  const payload = (review.payload ?? {}) as CombinePayload;
  const candidates = Array.isArray(payload.candidates)
    ? payload.candidates.map(narrowCandidate)
    : [];

  return (
    <div className="review-body review-body--combine" data-testid="combine-review-body">
      <div>
        <div style={{ fontSize: 11, opacity: 0.7 }}>candidates</div>
        {candidates.length === 0 ? (
          <span>—</span>
        ) : (
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
            {candidates.map((c, i) => (
              <li key={i} style={{ fontSize: 13, display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{ fontFamily: 'monospace' }}>{c.slug ?? '—'}</span>
                {c.display_name && <span style={{ opacity: 0.7 }}>{c.display_name}</span>}
                <StatusChip status={c.status} />
              </li>
            ))}
          </ul>
        )}
      </div>
      <p style={{ fontSize: 11, opacity: 0.7, margin: '8px 0 0' }}>
        Resolve payload:{' '}
        <code>{'{ "survivor_id": <id>, "absorbed_id": <id> }'}</code>
      </p>
    </div>
  );
}
