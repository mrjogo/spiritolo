import { useNeedsReview } from '../../reviews/useNeedsReview';

type NeedsReviewRow = ReturnType<typeof useNeedsReview>['rows'][number];

// A small free-text pill for the needs_review `reason` (origin/gate label).
// Reasons are open-ended, so we don't map them to StatusPill kinds — a plain
// neutral pill keeps this self-contained.
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

// The needs_review browser: the open review queue, grouped by pipeline stage.
// Reads the flattened needs_review summary rows via useNeedsReview() — the
// full stage_reviews row (state/origin/payload) is fetched elsewhere when an
// admin drills into an individual review, so this view stays a lightweight
// "what needs attention, and why" list.
export function ReviewsBrowser() {
  const { rows, status } = useNeedsReview();

  // Group by stage in first-seen order so the list reads as sections.
  const byStage = new Map<string, NeedsReviewRow[]>();
  for (const row of rows) {
    const list = byStage.get(row.stage);
    if (list) list.push(row);
    else byStage.set(row.stage, [row]);
  }

  return (
    <div className="ops-reviews">
      <p style={{ fontSize: 12, opacity: 0.7 }}>
        {status === 'loading'
          ? 'Loading…'
          : `${rows.length} item${rows.length === 1 ? '' : 's'} need review`}
      </p>

      {status !== 'loading' && rows.length === 0 && (
        <p style={{ fontStyle: 'italic', opacity: 0.7 }}>Nothing needs review.</p>
      )}

      {[...byStage.entries()].map(([stage, stageRows]) => (
        <section
          key={stage}
          aria-label={`${stage} reviews`}
          style={{ marginBottom: 16 }}
        >
          <h3 style={{ margin: '0 0 8px', fontSize: 14 }}>
            {stage} <span style={{ opacity: 0.6, fontWeight: 400 }}>({stageRows.length})</span>
          </h3>
          <ul
            role="list"
            style={{
              listStyle: 'none',
              margin: 0,
              padding: 0,
              display: 'flex',
              flexDirection: 'column',
              gap: 6,
            }}
          >
            {stageRows.map((row, i) => (
              <li
                key={`${row.entity_kind}:${row.entity_id}:${row.stage}:${i}`}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  fontSize: 13,
                  padding: '4px 0',
                  borderTop: '1px solid var(--ops-border, #eef0f3)',
                }}
              >
                <span style={{ opacity: 0.7 }}>{row.entity_kind}</span>
                <span style={{ fontFamily: 'monospace' }}>{row.entity_id}</span>
                <span style={{ fontSize: 11, opacity: 0.5 }}>{row.stage}</span>
                <ReasonPill reason={row.reason} />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
