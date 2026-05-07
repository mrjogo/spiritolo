import { useEffect, useState } from 'react';
import type { TaxonomyNode } from './shapeData';
import { TX_BROWN_INK, TX_BROWN_MID, TX_FRAME_EDGE } from './palette';
import { EditableField } from './EditableField';
import { AliasChipEditor } from './AliasChipEditor';
import { NODE_KIND_OPTIONS, DEFAULT_ROLE_OPTIONS } from './schemas';

export type NodeCardMode = 'hover' | 'pinned';

export type FieldKey =
  | 'display_name' | 'slug'
  | 'node_kind' | 'default_role'
  | 'is_cluster_node' | 'is_defining_garnish'
  | 'aliases';

export type ParentLookup = Map<number, { id: number; display_name: string }>;

interface Props {
  node: TaxonomyNode;
  mode: NodeCardMode;
  onDismiss: () => void;
  // Curator hooks (only meaningful in pinned mode; ignored in hover)
  onEditField?: (id: number, key: FieldKey, next: unknown) => Promise<void>;
  onEditParents?: (id: number) => void;
  onDelete?: (id: number) => void;
  parentLookup?: ParentLookup;
}

const yesNo = (b: boolean) => (b ? 'yes' : 'no');
// ui-monospace renders ~10–15% larger by character-cell metrics than the
// proportional serif at the same px size; bump down so values visually match.
const monoStyle: React.CSSProperties = { fontFamily: 'ui-monospace, monospace', fontSize: 13 };

export function NodeCard({ node, mode, onDismiss, onEditField, onEditParents, onDelete, parentLookup }: Props) {
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
        {mode === 'pinned' && onEditField ? (
          <>
            <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', padding: '2px 6px' }}>
              <span style={{ opacity: 0.7, fontSize: 10 }}>ID</span>
              <span style={{ ...monoStyle }}>{node.id}</span>
            </div>
            <EditableField
              label="DISPLAY NAME"
              kind="text"
              value={node.display_name}
              onSave={(v) => onEditField(node.id, 'display_name', v)}
            />
            <EditableField
              label="SLUG"
              kind="text"
              value={node.slug}
              onSave={(v) => onEditField(node.id, 'slug', v)}
            />
            <EditableField
              label="NODE KIND"
              kind="dropdown"
              value={node.node_kind ?? ''}
              options={[
                { value: '', label: '(none)' },
                ...NODE_KIND_OPTIONS.map((v) => ({ value: v, label: v })),
              ]}
              onSave={(v) => onEditField(node.id, 'node_kind', v === '' ? null : v)}
            />
            <EditableField
              label="DEFAULT ROLE"
              kind="dropdown"
              value={node.default_role ?? ''}
              options={[
                { value: '', label: '(none)' },
                ...DEFAULT_ROLE_OPTIONS.map((v) => ({ value: v, label: v })),
              ]}
              onSave={(v) => onEditField(node.id, 'default_role', v === '' ? null : v)}
            />
            <EditableField
              label="CLUSTER"
              kind="toggle"
              value={node.is_cluster_node}
              onSave={(v) => onEditField(node.id, 'is_cluster_node', v)}
            />
            <EditableField
              label="DEFINING GARNISH"
              kind="toggle"
              value={node.is_defining_garnish}
              onSave={(v) => onEditField(node.id, 'is_defining_garnish', v)}
            />
            <AliasChipEditor
              value={node.aliases}
              onSave={(v) => onEditField(node.id, 'aliases', v)}
            />
          </>
        ) : (
          // Hover mode (or pinned without onEditField): read-only PropertyGrid + ALIASES line
          <>
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
          </>
        )}

        {mode === 'pinned' && (
          <ParentsSection
            parentIds={node.parent_ids}
            parentLookup={parentLookup ?? new Map()}
            onEdit={onEditParents ? () => onEditParents(node.id) : undefined}
          />
        )}

        {mode === 'pinned' && (
          <div style={{ padding: '6px 8px', marginTop: 6 }}>
            <div className="tx-card__heading">
              CHILDREN · {node.child_ids.length}{' '}
              <span style={{ fontStyle: 'italic', color: TX_FRAME_EDGE, fontSize: 9 }}>
                (use + on graph to add)
              </span>
            </div>
          </div>
        )}

        <div className="tx-card__heading" style={{ marginTop: 10 }}>
          RECIPES <span style={{ fontStyle: 'italic', color: TX_FRAME_EDGE }}>({node.recipe_count})</span>
        </div>
        {node.recipe_count === 0 && <div>—</div>}
      </div>

      {mode === 'pinned' && onDelete && (
        <div style={{ padding: '8px 18px 14px', textAlign: 'right' }}>
          <button
            type="button"
            aria-label="delete node"
            onClick={() => onDelete(node.id)}
            style={{
              background: 'transparent', border: 'none', cursor: 'pointer',
              color: TX_BROWN_MID, opacity: 0.7,
              fontFamily: "'Cinzel', serif", fontSize: 10, letterSpacing: '0.18em',
              textTransform: 'uppercase',
            }}
          >Delete node</button>
        </div>
      )}
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

function ParentsSection({
  parentIds, parentLookup, onEdit,
}: {
  parentIds: number[];
  parentLookup: ParentLookup;
  onEdit?: () => void;
}) {
  const [hover, setHover] = useState(false);
  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        position: 'relative',
        padding: '6px 8px',
        marginTop: 10,
        border: hover ? '1px solid #8b6f3a' : '1px solid transparent',
        borderRadius: 3,
      }}
    >
      <div className="tx-card__heading">
        PARENTS · {parentIds.length}
      </div>
      {parentIds.map((pid) => {
        const p = parentLookup.get(pid);
        return (
          <div key={pid} style={{ padding: '2px 0' }}>
            {p?.display_name ?? `(${pid})`}{' '}
            <span style={{ fontFamily: 'ui-monospace, monospace', opacity: 0.5 }}>
              #{pid}
            </span>
          </div>
        );
      })}
      {onEdit && (
        <button
          type="button"
          aria-label="edit parents"
          onClick={onEdit}
          style={{
            position: 'absolute', top: 6, right: 8,
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: '#8b6f3a', padding: 0, lineHeight: 1, fontSize: 13,
            opacity: hover ? 1 : 0,
          }}
        >✎</button>
      )}
    </div>
  );
}
