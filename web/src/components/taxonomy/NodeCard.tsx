import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import type { TaxonomyNode } from './shapeData';
import { TX_BROWN_INK, TX_BROWN_MID, TX_FRAME_EDGE } from './palette';
import { supabase } from '../../supabase';
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
  /** Click-to-focus on a parent or child entry. Optional; missing means
   *  entries render non-interactive. */
  onFocusNode?: (id: number) => void;
  parentLookup?: ParentLookup;
}

type RecipeLink = { id: number; name: string | null; site: string };

const RECIPES_SELECT = 'recipe_id, recipes(id, name, site)';

// Match EditableField/AliasChipEditor row layout for the few static rows
// that don't go through those components (just the read-only ID).
const ID_ROW_STYLE: React.CSSProperties = {
  position: 'relative',
  padding: '6px 8px',
  display: 'grid',
  gridTemplateColumns: '132px 1fr',
  columnGap: 18,
  alignItems: 'baseline',
};
const ID_LABEL_STYLE: React.CSSProperties = {
  fontFamily: "'Cinzel', serif",
  fontSize: 10,
  letterSpacing: '0.18em',
  textTransform: 'uppercase',
  opacity: 0.7,
  textAlign: 'right',
  whiteSpace: 'nowrap',
};
function IdRow({ id }: { id: number }) {
  return (
    <div style={ID_ROW_STYLE} aria-label="ID">
      <span style={ID_LABEL_STYLE}>ID</span>
      <span style={{ textAlign: 'left' }}>{id}</span>
    </div>
  );
}

export function NodeCard({ node, mode, onDismiss, onEditField, onEditParents, onDelete, onFocusNode, parentLookup }: Props) {
  useEffect(() => {
    if (mode !== 'pinned') return;
    const handler = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      // If a modal is open above the card (Edit Parents, Create Child, Delete),
      // let it own this Escape — don't also dismiss the underlying card.
      if (document.querySelector('.tx-modal') !== null) return;
      onDismiss();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [mode, onDismiss]);

  const [recipes, setRecipes] = useState<RecipeLink[] | null>(null);
  const [recipesError, setRecipesError] = useState<string | null>(null);

  useEffect(() => {
    if (mode !== 'pinned') return;
    if (node.recipe_count === 0) return;
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setRecipes(null);
    setRecipesError(null);
    supabase
      .from('recipe_ingredients')
      .select(RECIPES_SELECT)
      .eq('taxonomy_node_id', node.id)
      .order('recipe_id', { ascending: true })
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error) {
          setRecipesError(error.message);
          return;
        }
        const seen = new Set<number>();
        const out: RecipeLink[] = [];
        for (const row of (data ?? []) as unknown as Array<{ recipe_id: number; recipes: { id: number; name: string | null; site: string } | null }>) {
          if (!row.recipes) continue;
          if (seen.has(row.recipes.id)) continue;
          seen.add(row.recipes.id);
          out.push(row.recipes);
        }
        out.sort((a, b) => {
          const sa = a.site.localeCompare(b.site);
          if (sa !== 0) return sa;
          return (a.name ?? '').localeCompare(b.name ?? '');
        });
        setRecipes(out);
      });
    return () => { cancelled = true; };
  }, [mode, node.id, node.recipe_count]);

  const readOnly = mode === 'hover';
  const handleEdit = onEditField ?? (async () => {});

  return (
    <aside
      className="tx-card"
      role={mode === 'pinned' ? 'dialog' : 'tooltip'}
      aria-label={`Taxonomy node: ${node.display_name}`}
      style={{
        position: 'relative',
        width: 290, padding: 0,
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

      {/* Title — fixed at top of card; never scrolls. The title itself is
          the display-name editor (no separate DISPLAY NAME row below). */}
      <div style={{ flex: '0 0 auto', padding: '20px 18px 0', textAlign: 'center' }}>
        <div className="tx-card__heading">— SPECIMEN —</div>
        <EditableTitle
          value={node.display_name}
          readOnly={readOnly}
          onSave={(v) => handleEdit(node.id, 'display_name', v)}
        />
        <div className="tx-rule" style={{ margin: '8px 16px' }} />
      </div>

      {/* Scrollable body — properties, neighbors, recipes. The whole area
          scrolls if it can't fit the viewport; the recipes list inside has
          its own min/max so it doesn't dominate when there are many. */}
      <div
        style={{
          flex: '1 1 auto',
          minHeight: 0,
          overflowY: 'auto',
          padding: '0 14px',
          fontSize: 15, lineHeight: 1.5, color: TX_BROWN_MID,
        }}
      >
        <IdRow id={node.id} />
        <EditableField
          label="SLUG"
          kind="text"
          value={node.slug}
          readOnly={readOnly}
          onSave={(v) => handleEdit(node.id, 'slug', v)}
        />
        <EditableField
          label="NODE KIND"
          kind="dropdown"
          value={node.node_kind ?? ''}
          readOnly={readOnly}
          options={[
            { value: '', label: '(none)' },
            ...NODE_KIND_OPTIONS.map((v) => ({ value: v, label: v })),
          ]}
          onSave={(v) => handleEdit(node.id, 'node_kind', v === '' ? null : v)}
        />
        <EditableField
          label="DEFAULT ROLE"
          kind="dropdown"
          value={node.default_role ?? ''}
          readOnly={readOnly}
          options={[
            { value: '', label: '(none)' },
            ...DEFAULT_ROLE_OPTIONS.map((v) => ({ value: v, label: v })),
          ]}
          onSave={(v) => handleEdit(node.id, 'default_role', v === '' ? null : v)}
        />
        <EditableField
          label="CLUSTER"
          kind="toggle"
          value={node.is_cluster_node}
          readOnly={readOnly}
          onSave={(v) => handleEdit(node.id, 'is_cluster_node', v)}
        />
        <EditableField
          label="DEFINING GARNISH"
          kind="toggle"
          value={node.is_defining_garnish}
          readOnly={readOnly}
          onSave={(v) => handleEdit(node.id, 'is_defining_garnish', v)}
        />
        <AliasChipEditor
          label="ALIASES"
          value={node.aliases}
          readOnly={readOnly}
          onSave={(v) => handleEdit(node.id, 'aliases', v)}
        />

        <NeighborSection
          heading="PARENTS"
          ids={node.parent_ids}
          lookup={parentLookup ?? new Map()}
          onEdit={!readOnly && onEditParents ? () => onEditParents(node.id) : undefined}
          onFocusNode={readOnly ? undefined : onFocusNode}
          editAriaLabel="edit parents"
        />

        <NeighborSection
          heading="CHILDREN"
          ids={node.child_ids}
          lookup={parentLookup ?? new Map()}
          onFocusNode={readOnly ? undefined : onFocusNode}
        />

        <div style={{ padding: '6px 8px', marginTop: 14 }}>
          <div className="tx-card__heading">
            RECIPES <span style={{ fontStyle: 'italic', color: TX_FRAME_EDGE }}>({node.recipe_count})</span>
          </div>
          {node.recipe_count === 0 && <div style={{ marginTop: 4 }}>—</div>}
          {mode === 'pinned' && node.recipe_count > 0 && recipesError !== null && (
            <div style={{ marginTop: 4, fontStyle: 'italic' }}>Couldn't load recipes</div>
          )}
          {mode === 'pinned' && node.recipe_count > 0 && recipes === null && recipesError === null && (
            <div style={{ marginTop: 4, fontStyle: 'italic' }}>Loading…</div>
          )}
          {mode === 'pinned' && node.recipe_count > 0 && recipes !== null && (
            <ul className="tx-card__recipes" style={{ margin: '6px 0 0' }}>
              {recipes.map((r) => (
                <li key={r.id}>
                  <Link to={`/recipes/${r.id}`}>{r.name ?? `recipe ${r.id}`}</Link>
                  <span className="tx-card__recipes-site">{r.site}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {mode === 'pinned' && onDelete && (
        <div style={{ flex: '0 0 auto', padding: '8px 18px 14px', textAlign: 'right' }}>
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

// Title that doubles as the display-name editor. Click the title to edit;
// Esc/blur cancels, Enter commits. No separate row below — the title IS
// the display-name field. Uppercase is purely visual; the underlying
// value is mixed-case so commits round-trip cleanly.
function EditableTitle({
  value, readOnly, onSave,
}: {
  value: string;
  readOnly: boolean;
  onSave: (next: string) => Promise<void> | void;
}) {
  const [hover, setHover] = useState(false);
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  async function commit(next: string) {
    setEditing(false);
    if (next === value) return;
    setPending(true);
    try {
      await onSave(next);
    } catch {
      setDraft(value);
    } finally {
      setPending(false);
    }
  }

  const titleStyle: React.CSSProperties = {
    fontFamily: "'Cinzel', serif",
    fontSize: 18,
    fontWeight: 700,
    letterSpacing: '0.18em',
    color: TX_BROWN_INK,
    textAlign: 'center',
    width: '100%',
  };

  if (editing) {
    return (
      <div style={{ marginTop: 4, position: 'relative' }}>
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void commit(draft);
            else if (e.key === 'Escape') {
              e.stopPropagation();
              setDraft(value);
              setEditing(false);
            }
          }}
          onBlur={() => void commit(draft)}
          style={{
            ...titleStyle,
            background: '#fff',
            border: '1px solid var(--tx-form-border-focus)',
            borderRadius: 'var(--tx-form-radius)',
            padding: '4px 10px',
            outline: 'none',
            textTransform: 'uppercase',
          }}
        />
      </div>
    );
  }

  if (readOnly) {
    return (
      <div style={{ ...titleStyle, marginTop: 4, padding: '4px 10px' }}>
        {value.toUpperCase()}
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      aria-label="edit display name"
      style={{
        ...titleStyle,
        marginTop: 4,
        padding: '4px 10px',
        position: 'relative',
        cursor: 'pointer',
        background: 'transparent',
        border: hover ? '1px solid var(--tx-form-border)' : '1px solid transparent',
        borderRadius: 'var(--tx-form-radius)',
        font: 'inherit',
      }}
    >
      <span style={titleStyle}>{value.toUpperCase()}</span>
      {pending && (
        <span
          aria-hidden
          style={{
            position: 'absolute', top: 8, right: 8,
            width: 10, height: 10, borderRadius: '50%',
            border: '1.5px solid var(--tx-form-border)', borderTopColor: 'transparent',
            animation: 'taxonomy-spin 0.9s linear infinite',
          }}
        />
      )}
      {hover && !pending && (
        <span
          aria-hidden
          style={{
            position: 'absolute', top: 4, right: 8,
            fontSize: 12, lineHeight: 1,
            color: 'var(--tx-brown-soft)',
            opacity: 0.65,
            pointerEvents: 'none',
          }}
        >
          ✎
        </span>
      )}
    </button>
  );
}

function NeighborSection({
  heading, ids, lookup, onEdit, onFocusNode, editAriaLabel,
}: {
  heading: string;
  ids: number[];
  lookup: ParentLookup;
  onEdit?: () => void;
  onFocusNode?: (id: number) => void;
  editAriaLabel?: string;
}) {
  // Hover applies across the whole section (heading + items list) so the
  // pencil reveals on intent, not on a hairline-thin heading row.
  const [hover, setHover] = useState(false);
  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        position: 'relative',
        padding: '6px 8px',
        marginTop: 14,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, position: 'relative' }}>
        <div className="tx-card__heading">
          {heading} · {ids.length}
        </div>
        {onEdit && (
          <button
            type="button"
            aria-label={editAriaLabel ?? `edit ${heading.toLowerCase()}`}
            onClick={onEdit}
            style={{
              background: 'transparent', border: 'none', cursor: 'pointer',
              color: '#8b6f3a', padding: 0, lineHeight: 1, fontSize: 13,
              opacity: hover ? 1 : 0,
              transition: 'opacity 120ms ease',
            }}
          >✎</button>
        )}
      </div>
      <ul style={{ listStyle: 'none', padding: 0, margin: '4px 0 0' }}>
        {ids.map((nid) => {
          const name = lookup.get(nid)?.display_name ?? 'unknown';
          const text = `${name} (id: ${nid})`;
          if (onFocusNode) {
            return (
              <li key={nid}>
                <button
                  type="button"
                  className="tx-link"
                  onClick={() => onFocusNode(nid)}
                  style={{
                    display: 'block', width: '100%', textAlign: 'left',
                    padding: '2px 0', background: 'transparent', border: 'none',
                    font: 'inherit', cursor: 'pointer',
                  }}
                >
                  {text}
                </button>
              </li>
            );
          }
          return (
            <li key={nid} style={{ padding: '2px 0' }}>
              {text}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
