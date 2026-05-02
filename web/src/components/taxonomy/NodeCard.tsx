import { useEffect } from 'react';
import type { TaxonomyNode } from './shapeData';
import { TX_BROWN_INK, TX_BROWN_MID, TX_FRAME_EDGE } from './palette';

export type NodeCardMode = 'hover' | 'pinned';

interface Props {
  node: TaxonomyNode;
  mode: NodeCardMode;
  onDismiss: () => void;
}

const yesNo = (b: boolean) => (b ? 'yes' : 'no');

export function NodeCard({ node, mode, onDismiss }: Props) {
  useEffect(() => {
    if (mode !== 'pinned') return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onDismiss(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [mode, onDismiss]);

  const copySlug = async () => {
    try { await navigator.clipboard.writeText(node.slug); } catch { /* swallow */ }
  };

  return (
    <aside
      className="tx-card"
      role={mode === 'pinned' ? 'dialog' : 'tooltip'}
      aria-label={`Taxonomy node: ${node.display_name}`}
      style={{ width: 240, padding: '20px 18px' }}
    >
      {mode === 'pinned' && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Close"
          style={{
            position: 'absolute', top: 6, right: 8,
            background: 'none', border: 'none', cursor: 'pointer',
            color: TX_BROWN_MID, fontSize: 16, lineHeight: 1,
            fontFamily: "'Cinzel', serif",
          }}
        >
          ×
        </button>
      )}

      <div style={{ textAlign: 'center' }}>
        <div className="tx-card__heading">— SPECIMEN —</div>
        <div
          style={{
            fontFamily: "'Cinzel', serif", fontSize: 16, fontWeight: 700,
            letterSpacing: '0.18em', color: TX_BROWN_INK, marginTop: 4,
          }}
        >
          {node.display_name.toUpperCase()}
        </div>
        <div className="tx-rule" style={{ margin: '8px 16px' }} />
      </div>

      <div style={{ fontSize: 13, lineHeight: 1.55, color: TX_BROWN_MID }}>
        <div className="tx-card__heading" style={{ marginTop: 4 }}>PROPERTIES</div>
        <Row label="ID" value={String(node.id)} />
        <Row label="Node kind" value={node.node_kind ?? '—'} />
        <Row label="Default ingredient role" value={node.default_role ?? '—'} />
        <Row label="Clustering node" value={yesNo(node.is_cluster_node)} />
        <Row label="Defining garnish" value={yesNo(node.is_defining_garnish)} />
        <Row
          label="Slug"
          value={
            <button
              type="button"
              onClick={copySlug}
              aria-label={`Copy slug ${node.slug} to clipboard`}
              style={{
                background: 'none', border: 'none', padding: 0,
                color: 'inherit', textAlign: 'right',
                fontFamily: 'ui-monospace, monospace', fontSize: 12,
                cursor: 'pointer', userSelect: 'none',
              }}
            >
              {node.slug}
            </button>
          }
        />

        <div className="tx-card__heading" style={{ marginTop: 10 }}>
          ALIASES <span style={{ fontStyle: 'italic', color: TX_FRAME_EDGE }}>({node.aliases.length})</span>
        </div>
        <div>{node.aliases.length > 0 ? node.aliases.join(', ') : '—'}</div>

        <div className="tx-card__heading" style={{ marginTop: 10 }}>
          RECIPES <span style={{ fontStyle: 'italic', color: TX_FRAME_EDGE }}>({node.recipe_count})</span>
        </div>
        {node.recipe_count === 0 && <div>—</div>}
      </div>
    </aside>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
      <span>{label}</span>
      <span style={{ textAlign: 'right' }}>{value}</span>
    </div>
  );
}
