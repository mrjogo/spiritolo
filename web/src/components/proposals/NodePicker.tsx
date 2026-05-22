// Single-select typeahead over taxonomy_public. Mirrors the keyboard +
// scroll-list idiom of EditParentsModal (web/src/components/taxonomy/
// EditParentsModal.tsx); kept separate because that component is
// multi-select inside a modal and extracting a shared inner picker
// would not be a mechanical change. If a third call site shows up,
// reconsider extracting.
import { useMemo, useRef, useState } from 'react';

export interface PickerNode {
  id: number;
  slug: string;
  display_name: string;
  aliases: string[];
}

interface Props {
  nodes: PickerNode[];
  value: number | null;
  onChange: (id: number) => void;
}

const RESULTS_HEIGHT = 220;

export function NodePicker({ nodes, value, onChange }: Props) {
  const [query, setQuery] = useState('');
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const eligible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const pool = nodes.filter((n) => {
      if (q === '') return true;
      if (n.display_name.toLowerCase().includes(q)) return true;
      if (n.slug.toLowerCase().includes(q)) return true;
      if (n.aliases.some((a) => a.toLowerCase().includes(q))) return true;
      return false;
    });
    pool.sort((a, b) => a.display_name.localeCompare(b.display_name));
    return pool;
  }, [nodes, query]);

  return (
    <div>
      <input
        ref={inputRef}
        type="text"
        className="tx-input"
        aria-label="search nodes"
        value={query}
        placeholder="search by name, slug, or alias…"
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
            if (target) onChange(target.id);
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
          eligible.map((n, i) => {
            const selected = value === n.id;
            const highlighted = i === highlight;
            return (
              <div
                key={n.id}
                role="option"
                aria-selected={selected}
                onMouseEnter={() => setHighlight(i)}
                onClick={() => onChange(n.id)}
                style={{
                  padding: '6px 10px',
                  cursor: 'pointer',
                  background: highlighted
                    ? 'rgba(201, 164, 73, 0.18)'
                    : selected
                      ? 'rgba(201, 164, 73, 0.10)'
                      : 'transparent',
                }}
              >
                {n.display_name} · {n.slug}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
