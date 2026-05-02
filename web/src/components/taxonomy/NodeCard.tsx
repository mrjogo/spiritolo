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
const monoStyle: React.CSSProperties = { fontFamily: 'ui-monospace, monospace' };

export function NodeCard({ node, mode, onDismiss }: Props) {
  useEffect(() => {
    if (mode !== 'pinned') return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onDismiss(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [mode, onDismiss]);

  return (
    <aside
      className="tx-card"
      role={mode === 'pinned' ? 'dialog' : 'tooltip'}
      aria-label={`Taxonomy node: ${node.display_name}`}
      style={{
        position: 'relative',
        width: 240, padding: 0,
        maxHeight: '100%', minHeight: 0,
        display: 'flex', flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {mode === 'pinned' && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Close"
          style={{
            position: 'absolute', top: 6, right: 8, zIndex: 1,
            background: 'none', border: 'none', cursor: 'pointer',
            color: TX_BROWN_MID, fontSize: 16, lineHeight: 1,
            fontFamily: "'Cinzel', serif",
          }}
        >
          ×
        </button>
      )}

      <div style={{ flex: '0 0 auto', padding: '20px 18px 0', textAlign: 'center' }}>
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

      <div
        style={{
          flex: '1 1 auto', minHeight: 0, overflowY: 'auto',
          padding: '0 18px 20px',
          fontSize: 13, lineHeight: 1.55, color: TX_BROWN_MID,
        }}
      >
        <div className="tx-card__heading" style={{ marginTop: 4 }}>PROPERTIES</div>
        <Row label="ID" value={String(node.id)} valueStyle={monoStyle} />
        <Row label="Slug" value={node.slug} valueStyle={monoStyle} />
        <Row label="Node kind" value={node.node_kind ?? '—'} />
        <Row label="Default ingredient role" value={node.default_role ?? '—'} />
        <Row label="Clustering node" value={yesNo(node.is_cluster_node)} />
        <Row label="Defining garnish" value={yesNo(node.is_defining_garnish)} />

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

function Row({
  label, value, valueStyle,
}: {
  label: string;
  value: React.ReactNode;
  valueStyle?: React.CSSProperties;
}) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
      <span style={{ flex: '0 0 auto' }}>{label}</span>
      <span style={{ textAlign: 'right', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', ...valueStyle }}>{value}</span>
    </div>
  );
}
