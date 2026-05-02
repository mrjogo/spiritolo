import { useEffect } from 'react';
import type { TaxonomyNode } from './shapeData';
import { TX_BROWN_INK, TX_BROWN_MID } from './palette';

export type EdgeCardMode = 'hover' | 'pinned';

export interface EdgeRef {
  source: TaxonomyNode;
  target: TaxonomyNode;
}

interface Props {
  edge: EdgeRef;
  mode: EdgeCardMode;
  onDismiss: () => void;
  onFocusNode?: (id: number) => void;
}

const monoStyle: React.CSSProperties = { fontFamily: 'ui-monospace, monospace', fontSize: 13 };

export function EdgeCard({ edge, mode, onDismiss, onFocusNode }: Props) {
  useEffect(() => {
    if (mode !== 'pinned') return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onDismiss(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [mode, onDismiss]);

  const focus = (id: number) => {
    if (onFocusNode) onFocusNode(id);
  };

  return (
    <aside
      className="tx-card"
      role={mode === 'pinned' ? 'dialog' : 'tooltip'}
      aria-label={`Taxonomy edge: ${edge.source.display_name} → ${edge.target.display_name}`}
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
        <div className="tx-card__heading">— EDGE —</div>
        <div
          style={{
            fontFamily: "'Cinzel', serif", fontSize: 14, fontWeight: 700,
            letterSpacing: '0.12em', color: TX_BROWN_INK, marginTop: 4,
            wordBreak: 'break-word',
          }}
        >
          <NodeLink name={edge.source.display_name} onClick={() => focus(edge.source.id)} />
          <div
            style={{
              fontFamily: "'Cormorant Garamond', Georgia, serif",
              fontStyle: 'italic', fontWeight: 400,
              fontSize: 13, letterSpacing: 0,
              color: TX_BROWN_MID, margin: '4px 0',
            }}
          >
            to
          </div>
          <NodeLink name={edge.target.display_name} onClick={() => focus(edge.target.id)} />
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
        <Row
          label="ID"
          value={`(${edge.source.id}, ${edge.target.id})`}
          valueStyle={monoStyle}
        />
      </div>
    </aside>
  );
}

function NodeLink({ name, onClick }: { name: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        background: 'none', border: 'none', padding: 0, margin: 0,
        font: 'inherit', color: 'inherit', letterSpacing: 'inherit',
        cursor: 'pointer', textAlign: 'center', wordBreak: 'break-word',
      }}
    >
      {name.toUpperCase()}
    </button>
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
      <span style={{ textAlign: 'right', minWidth: 0, ...valueStyle }}>{value}</span>
    </div>
  );
}
