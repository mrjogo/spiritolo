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
}

export function EdgeCard({ edge, mode, onDismiss }: Props) {
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
      aria-label={`Taxonomy edge: ${edge.source.display_name} → ${edge.target.display_name}`}
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
        <div className="tx-card__heading">— EDGE —</div>
        <div
          style={{
            fontFamily: "'Cinzel', serif", fontSize: 13, fontWeight: 700,
            letterSpacing: '0.12em', color: TX_BROWN_INK, marginTop: 4,
          }}
        >
          {edge.source.display_name.toUpperCase()}
          <span style={{ margin: '0 6px' }}>→</span>
          {edge.target.display_name.toUpperCase()}
        </div>
        <div className="tx-rule" style={{ margin: '8px 16px' }} />
      </div>

      <div style={{ fontSize: 13, lineHeight: 1.55, color: TX_BROWN_MID }}>
        <div className="tx-card__heading" style={{ marginTop: 4 }}>PROPERTIES</div>
        <Row label="Source ID" value={String(edge.source.id)} />
        <Row label="Target ID" value={String(edge.target.id)} />
      </div>
    </aside>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
      <span>{label}</span>
      <span style={{ textAlign: 'right' }}>{value}</span>
    </div>
  );
}
