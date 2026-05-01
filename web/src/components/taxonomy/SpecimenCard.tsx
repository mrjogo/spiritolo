import { useEffect } from 'react';
import type { TaxonomyNode } from './shapeData';
import { TX_BROWN_INK, TX_BROWN_MID, TX_BROWN_FAINT, TX_FRAME_EDGE } from './palette';

interface Props {
  node: TaxonomyNode;
  onDismiss: () => void;
}

export function SpecimenCard({ node, onDismiss }: Props) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onDismiss(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onDismiss]);

  const copySlug = async () => {
    try { await navigator.clipboard.writeText(node.slug); } catch { /* swallow */ }
  };

  return (
    <aside
      className="tx-card"
      role="dialog"
      aria-label={`Taxonomy specimen: ${node.display_name}`}
      style={{
        position: 'absolute', top: 0, right: 0, bottom: 0, width: 240, zIndex: 4,
        padding: '20px 18px', borderRadius: 0, borderRight: 'none',
      }}
    >
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
        <Row label="role" value={node.role ?? '—'} />
        <Row label="role default" value={node.role_default ?? '—'} />
        <Row label="cluster node" value={node.is_cluster_node ? '✓' : '—'} />
        <Row label="defining garnish" value={node.is_defining_garnish ? '✓' : '—'} />

        <div className="tx-card__heading" style={{ marginTop: 10 }}>
          ALIASES <span style={{ fontStyle: 'italic', color: TX_FRAME_EDGE }}>({node.aliases.length})</span>
        </div>
        <div style={{ fontStyle: 'italic' }}>{node.aliases.join(', ') || '—'}</div>

        <div className="tx-card__heading" style={{ marginTop: 10 }}>RECIPES</div>
        <div>{node.recipe_count} drinks call for this</div>

        <div className="tx-card__heading" style={{ marginTop: 10 }}>SLUG</div>
        <button
          type="button"
          onClick={copySlug}
          aria-label={`Copy slug ${node.slug} to clipboard`}
          style={{
            background: 'none', border: 'none', padding: 0,
            color: 'inherit', textAlign: 'left',
            fontFamily: 'ui-monospace, monospace', fontSize: 12,
            cursor: 'pointer', userSelect: 'none',
          }}
        >
          ⊕ {node.slug}
        </button>
      </div>

      <div
        style={{
          position: 'absolute', left: 0, right: 0, bottom: 16, textAlign: 'center',
          fontFamily: "'Cinzel', serif", fontSize: 9, letterSpacing: '0.3em', color: TX_BROWN_FAINT,
        }}
      >
        ESC TO DISMISS
      </div>
    </aside>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
      <span>{label}</span>
      <span style={{ fontStyle: 'italic' }}>{value}</span>
    </div>
  );
}
