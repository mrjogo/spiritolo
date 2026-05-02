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
// ui-monospace renders ~10–15% larger by character-cell metrics than the
// proportional serif at the same px size; bump down so values visually match.
const monoStyle: React.CSSProperties = { fontFamily: 'ui-monospace, monospace', fontSize: 13 };

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
            fontFamily: "'Cinzel', serif", fontSize: 18, fontWeight: 700,
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
          fontSize: 15, lineHeight: 1.5, color: TX_BROWN_MID,
        }}
      >
        <div className="tx-card__heading" style={{ marginTop: 4 }}>PROPERTIES</div>
        <PropertyGrid>
          <Cell label="ID">
            <span style={monoStyle}>{node.id}</span>
          </Cell>
          <Cell label="Slug">
            <span style={{ ...monoStyle, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>
              {node.slug}
            </span>
          </Cell>
          <Cell label="Node kind">{node.node_kind ?? '—'}</Cell>
          <Cell label="Default ingredient role">{node.default_role ?? '—'}</Cell>
          <Cell label="Clustering node">{yesNo(node.is_cluster_node)}</Cell>
          <Cell label="Defining garnish">{yesNo(node.is_defining_garnish)}</Cell>
        </PropertyGrid>

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

// Two-column grid: labels share a max-content column so all values
// align on the same left edge. Children must come in pairs (Cell
// renders both columns in one go).
function PropertyGrid({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'max-content 1fr',
        columnGap: 12,
        rowGap: 0,
        alignItems: 'baseline',
      }}
    >
      {children}
    </div>
  );
}

function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <span>{label}</span>
      <span style={{ textAlign: 'right', minWidth: 0 }}>{children}</span>
    </>
  );
}
