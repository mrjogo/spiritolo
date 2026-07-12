import { useMemo, useRef, useState } from 'react';
import type { TaxonomyViewRow } from './shapeData';
import { descendantsOf } from './cycle';
import { ModalShell } from '../../ui/Modal';

interface Props {
  node: TaxonomyViewRow;
  currentParentIds: number[];
  rows: TaxonomyViewRow[];
  onCancel: () => void;
  onSave: (id: number, parentIds: number[]) => Promise<void> | void;
}

const RESULTS_HEIGHT = 220;

export function EditParentsModal({ node, currentParentIds, rows, onCancel, onSave }: Props) {
  const [selectedIds, setSelectedIds] = useState<number[]>(currentParentIds);
  const [query, setQuery] = useState('');
  const [highlight, setHighlight] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Self + descendants are silently filtered from the result list — choosing
  // one would create a cycle in the DAG, so the user shouldn't see them as
  // options at all.
  const blocked = useMemo(() => {
    const desc = descendantsOf(node.id, rows);
    desc.add(node.id);
    return desc;
  }, [node.id, rows]);

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  // Permanent result list: when the query is empty, all eligible nodes
  // sorted alphabetically (the user can scroll). With a query, the same
  // pool filtered by substring match on name or slug.
  const eligible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const pool = rows
      .filter((r) => !blocked.has(r.id) && !selectedSet.has(r.id))
      .filter((r) => q === '' || r.display_name.toLowerCase().includes(q) || r.slug.toLowerCase().includes(q));
    pool.sort((a, b) => a.display_name.localeCompare(b.display_name));
    return pool;
  }, [query, rows, blocked, selectedSet]);

  const dirty = !sameIds(currentParentIds, selectedIds);

  function add(id: number) {
    if (blocked.has(id) || selectedSet.has(id)) return;
    setSelectedIds([...selectedIds, id]);
    setQuery('');
    setHighlight(0);
    inputRef.current?.focus();
  }

  function remove(id: number) {
    setSelectedIds(selectedIds.filter((x) => x !== id));
    inputRef.current?.focus();
  }

  async function save() {
    setSubmitting(true);
    try {
      await onSave(node.id, selectedIds);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalShell onBackdropClick={onCancel}>
      <h2 className="tx-modal__title">Edit parents of {node.display_name}</h2>

      {/* Selected chips — sit above the search bar, not inside it. The
          chips area always renders so the popup doesn't change height
          when you add or remove parents. */}
      <div className="tx-field">
        <label className="tx-field__label">Selected</label>
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 6,
            alignItems: 'center',
            minHeight: 28,
            padding: '4px 0',
          }}
        >
          {selectedIds.length === 0 ? (
            <span style={{ fontStyle: 'italic', opacity: 0.55, fontSize: 13 }}>none</span>
          ) : (
            selectedIds.map((id) => {
              const r = rows.find((x) => x.id === id);
              const name = r?.display_name ?? `unknown (${id})`;
              return (
                <span key={id} className="tx-chip">
                  {name}
                  <button
                    type="button"
                    aria-label={`remove ${name}`}
                    onClick={() => remove(id)}
                    className="tx-chip__remove"
                  >×</button>
                </span>
              );
            })
          )}
        </div>
      </div>

      {/* Search input + permanent scrolling result list. The list is
          always visible; typing filters its contents. The list height is
          fixed so the popup never changes size. */}
      <div className="tx-field">
        <input
          ref={inputRef}
          type="text"
          className="tx-input"
          value={query}
          placeholder="search by name or slug…"
          autoFocus
          onChange={(e) => { setQuery(e.target.value); setHighlight(0); }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault();
              setHighlight((h) => Math.min(h + 1, eligible.length - 1));
            } else if (e.key === 'ArrowUp') {
              e.preventDefault();
              setHighlight((h) => Math.max(h - 1, 0));
            } else if (e.key === 'Enter') {
              e.preventDefault();
              const target = eligible[highlight];
              if (target) add(target.id);
            }
          }}
        />
        <div
          role="listbox"
          style={{
            marginTop: 6,
            background: 'var(--tx-form-bg)',
            border: '1px solid var(--tx-form-border)',
            borderRadius: 'var(--tx-form-radius)',
            height: RESULTS_HEIGHT,
            overflowY: 'auto',
          }}
        >
          {eligible.length === 0 ? (
            <div style={{ padding: 12, fontStyle: 'italic', opacity: 0.6, fontSize: 13 }}>
              no matches
            </div>
          ) : (
            eligible.map((r, i) => {
              const highlighted = i === highlight;
              return (
                <div
                  key={r.id}
                  role="option"
                  aria-selected={highlighted}
                  onMouseDown={(e) => { e.preventDefault(); add(r.id); }}
                  onMouseEnter={() => setHighlight(i)}
                  style={{
                    padding: '6px 12px',
                    background: highlighted ? 'rgba(201, 164, 73, 0.18)' : 'transparent',
                    cursor: 'pointer',
                    fontSize: 13,
                    color: 'var(--tx-brown-ink)',
                  }}
                >
                  {r.display_name}{' '}
                  <span style={{ opacity: 0.55, fontSize: 12 }}>(id: {r.id})</span>
                </div>
              );
            })
          )}
        </div>
      </div>

      <div className="tx-form-actions">
        <button type="button" className="tx-btn tx-btn--ghost" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="tx-btn tx-btn--primary"
          onClick={() => void save()}
          disabled={submitting || !dirty}
        >
          Save
        </button>
      </div>
    </ModalShell>
  );
}

function sameIds(a: number[], b: number[]) {
  if (a.length !== b.length) return false;
  const sa = [...a].sort();
  const sb = [...b].sort();
  for (let i = 0; i < sa.length; i++) if (sa[i] !== sb[i]) return false;
  return true;
}
