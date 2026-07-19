import type { StageReview } from '../ReviewCard';

// Read-only body for a `connect-nodes`-stage review: a machine proposal to
// place + promote a provisional node. Shows the candidate parents the connector
// considered (slug, display name) and any rejected `proposed` placement.
// Payload is untyped jsonb off the human_reviews row, so every field is
// narrowed defensively.
//
// Resolving means writing a placement payload for the node (this review's
// entity_id) — see the hint line below.
interface ParentCandidate {
  slug: string | null;
  display_name: string | null;
}

interface ConnectPayload {
  candidate_parents?: unknown;
  proposed?: unknown;
}

function narrowParent(c: unknown): ParentCandidate {
  if (c && typeof c === 'object') {
    const obj = c as Record<string, unknown>;
    return {
      slug: typeof obj.slug === 'string' ? obj.slug : null,
      display_name: typeof obj.display_name === 'string' ? obj.display_name : null,
    };
  }
  return { slug: null, display_name: null };
}

export function ConnectReviewBody({ review }: { review: StageReview }) {
  const payload = (review.payload ?? {}) as ConnectPayload;
  const parents = Array.isArray(payload.candidate_parents)
    ? payload.candidate_parents.map(narrowParent)
    : [];
  const proposed =
    payload.proposed && typeof payload.proposed === 'object' ? payload.proposed : null;

  return (
    <div className="review-body review-body--connect" data-testid="connect-review-body">
      <div>
        <div style={{ fontSize: 11, opacity: 0.7 }}>candidate parents</div>
        {parents.length === 0 ? (
          <span>—</span>
        ) : (
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
            {parents.map((p, i) => (
              <li key={i} style={{ fontSize: 13, display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{ fontFamily: 'monospace' }}>{p.slug ?? '—'}</span>
                {p.display_name && <span style={{ opacity: 0.7 }}>{p.display_name}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
      {proposed && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11, opacity: 0.7 }}>proposed (rejected)</div>
          <pre
            style={{
              margin: '4px 0 0',
              fontFamily: 'monospace',
              fontSize: 12,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {JSON.stringify(proposed, null, 2)}
          </pre>
        </div>
      )}
      <p style={{ fontSize: 11, opacity: 0.7, margin: '8px 0 0' }}>
        Resolve payload:{' '}
        <code>
          {'{ "node_kind": "brand"|"expression"|null, "parent_slugs": [...], "is_cluster_node": <bool> }'}
        </code>
      </p>
    </div>
  );
}
