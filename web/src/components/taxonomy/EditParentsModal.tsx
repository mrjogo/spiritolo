import { useMemo, useState } from 'react';
import type { TaxonomyViewRow } from './shapeData';
import { descendantsOf } from './cycle';
import { ModalShell } from './CreateChildModal';

interface Props {
  node: TaxonomyViewRow;
  currentParentIds: number[];
  rows: TaxonomyViewRow[];
  onCancel: () => void;
  onSave: (id: number, parentIds: number[]) => Promise<void> | void;
}

export function EditParentsModal({ node, currentParentIds, rows, onCancel, onSave }: Props) {
  const [removed, setRemoved] = useState<Set<number>>(new Set());
  const [added, setAdded] = useState<number[]>([]);
  const [query, setQuery] = useState('');
  const [highlight, setHighlight] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  const blocked = useMemo(() => {
    const desc = descendantsOf(node.id, rows);
    desc.add(node.id);
    return desc;
  }, [node.id, rows]);

  const stagedSet = useMemo(() => {
    const s = new Set(currentParentIds.filter((id) => !removed.has(id)));
    for (const a of added) s.add(a);
    return s;
  }, [currentParentIds, removed, added]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q === '') return [];
    return rows
      .filter((r) =>
        r.display_name.toLowerCase().includes(q) ||
        r.slug.toLowerCase().includes(q),
      )
      .slice(0, 20);
  }, [query, rows]);

  function toggleRemove(id: number) {
    setRemoved((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function addParent(id: number) {
    if (blocked.has(id)) return;
    if (stagedSet.has(id)) return;
    setAdded((a) => [...a, id]);
    setQuery('');
    setHighlight(0);
  }

  function unstageAdded(id: number) {
    setAdded((a) => a.filter((x) => x !== id));
  }

  async function save() {
    setSubmitting(true);
    try {
      await onSave(node.id, Array.from(stagedSet));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalShell onBackdropClick={onCancel}>
      <h2 className="tx-modal__title">Edit parents of {node.display_name}</h2>
      <div className="tx-modal__subtitle">
        {currentParentIds.length} CURRENT · +{added.length} STAGED ·{' '}
        {removed.size > 0 ? `-${removed.size} REMOVED · ` : ''}
        {(removed.size > 0 || added.length > 0) ? 'UNSAVED' : 'CLEAN'}
      </div>

      <div className="tx-modal__label">CURRENT PARENTS</div>
      {currentParentIds.map((pid) => {
        const r = rows.find((row) => row.id === pid);
        const isRemoved = removed.has(pid);
        return (
          <ParentRow
            key={pid}
            name={r?.display_name ?? '(unknown)'}
            idLabel={`#${pid}`}
            removed={isRemoved}
            ariaLabel={isRemoved ? `undo remove ${r?.display_name ?? pid}` : `remove ${r?.display_name ?? pid}`}
            onClick={() => toggleRemove(pid)}
          />
        );
      })}
      {added.map((id) => {
        const r = rows.find((row) => row.id === id);
        return (
          <ParentRow
            key={`added-${id}`}
            name={r?.display_name ?? '(unknown)'}
            idLabel={`#${id}`}
            staged
            ariaLabel={`unstage ${r?.display_name ?? id}`}
            onClick={() => unstageAdded(id)}
          />
        );
      })}

      {blocked.size > 1 && (
        <div style={{ marginTop: 8, fontSize: 10, color: '#888' }}>
          {Array.from(blocked)
            .filter((id) => id !== node.id)
            .map((id) => {
              const r = rows.find((row) => row.id === id);
              return (
                <span key={id} style={{ marginRight: 6 }}>
                  {r?.display_name ?? id}{' '}
                  <em>would create cycle</em>
                </span>
              );
            })}
        </div>
      )}

      <div className="tx-modal__label" style={{ marginTop: 12 }}>ADD PARENT</div>
      <input
        type="text"
        value={query}
        placeholder="search by name or slug..."
        onChange={(e) => { setQuery(e.target.value); setHighlight(0); }}
        onKeyDown={(e) => {
          const eligible = results.filter((r) => !blocked.has(r.id) && !stagedSet.has(r.id));
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setHighlight((h) => Math.min(h + 1, eligible.length - 1));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setHighlight((h) => Math.max(h - 1, 0));
          } else if (e.key === 'Enter') {
            e.preventDefault();
            const target = eligible[highlight];
            if (target) addParent(target.id);
          }
        }}
      />
      {results.length > 0 && (
        <div style={{ background: 'white', border: '1px solid #b8924d', maxHeight: 160, overflow: 'auto', marginTop: 4 }}>
          {results.map((r, i) => {
            const cycle = blocked.has(r.id);
            const already = stagedSet.has(r.id);
            const eligibleIdx = results
              .slice(0, i + 1)
              .filter((x) => !blocked.has(x.id) && !stagedSet.has(x.id))
              .length - 1;
            const highlighted = !cycle && !already && eligibleIdx === highlight;
            return (
              <div
                key={r.id}
                onClick={() => addParent(r.id)}
                style={{
                  padding: '4px 8px',
                  background: highlighted ? '#faf5e6' : 'transparent',
                  cursor: cycle || already ? 'not-allowed' : 'pointer',
                  opacity: cycle || already ? 0.5 : 1,
                  display: 'flex', justifyContent: 'space-between',
                }}
              >
                <span>
                  {r.display_name}
                  {cycle && <em style={{ marginLeft: 6, fontSize: 10 }}>would create cycle</em>}
                  {already && !cycle && <em style={{ marginLeft: 6, fontSize: 10 }}>already added</em>}
                </span>
                <span style={{ fontFamily: 'ui-monospace, monospace', opacity: 0.5 }}>#{r.id}</span>
              </div>
            );
          })}
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
        <button type="button" onClick={onCancel}>CANCEL</button>
        <button
          type="button"
          onClick={() => void save()}
          disabled={submitting || (removed.size === 0 && added.length === 0)}
        >SAVE</button>
      </div>
    </ModalShell>
  );
}

function ParentRow({
  name, idLabel, removed, staged, ariaLabel, onClick,
}: {
  name: string;
  idLabel: string;
  removed?: boolean;
  staged?: boolean;
  ariaLabel: string;
  onClick: () => void;
}) {
  return (
    <div
      style={{
        display: 'flex', alignItems: 'center',
        padding: '6px 8px', marginBottom: 4,
        background: staged ? '#faf5e6' : 'white',
        border: staged ? '1px dashed #b8924d' : '1px solid #b8924d',
        textDecoration: removed ? 'line-through' : 'none',
        opacity: removed ? 0.6 : 1,
        fontSize: 11,
      }}
    >
      <span style={{ flex: 1, display: 'flex', gap: 4 }}>
        <span>{name}</span>
        <span style={{ fontFamily: 'ui-monospace, monospace', opacity: 0.5 }}>{idLabel}</span>
      </span>
      <button
        type="button"
        aria-label={ariaLabel}
        onClick={onClick}
        style={{ background: 'transparent', border: 'none', color: removed ? '#2a7a3a' : '#c44', cursor: 'pointer', fontSize: 14, lineHeight: 1 }}
      >{removed ? '↩' : '×'}</button>
    </div>
  );
}
