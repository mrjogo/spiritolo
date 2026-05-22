import { useMemo, useState } from 'react';
import type { PendingProposal, ParentBucket } from './schemas';

interface Props {
  proposals: PendingProposal[];
  parents: ParentBucket[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

const ALL = '__all__';

export function ProposalList({ proposals, parents, selectedId, onSelect }: Props) {
  const [filterParent, setFilterParent] = useState<string>(ALL);

  const filtered = useMemo(() => {
    if (filterParent === ALL) return proposals;
    return proposals.filter(
      (p) => (p.proposed_parent_display_name ?? '(none)') === filterParent,
    );
  }, [proposals, filterParent]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '8px 12px', borderBottom: '1px solid var(--tx-form-border)',
      }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="tx-field__label" style={{ margin: 0 }}>
            Filter by parent
          </span>
          <select
            aria-label="filter by parent"
            value={filterParent}
            onChange={(e) => setFilterParent(e.target.value)}
            className="tx-select"
          >
            <option value={ALL}>all parents</option>
            {parents.map((p) => {
              const label = p.proposed_parent_display_name ?? '(none)';
              return (
                <option key={label} value={label}>
                  {label} ({p.pending_count})
                </option>
              );
            })}
          </select>
        </label>
        <div style={{ fontVariantNumeric: 'tabular-nums', opacity: 0.8 }}>
          {proposals.length} pending
        </div>
      </div>

      <ul
        role="listbox"
        style={{
          listStyle: 'none', padding: 0, margin: 0,
          overflowY: 'auto', flex: 1,
        }}
      >
        {filtered.map((p) => {
          const selected = p.id === selectedId;
          return (
            <li
              key={p.id}
              role="option"
              aria-selected={selected}
              onClick={() => onSelect(p.id)}
              style={{
                padding: '8px 12px',
                borderBottom: '1px solid var(--tx-form-border)',
                cursor: 'pointer',
                background: selected ? 'rgba(201, 164, 73, 0.18)' : 'transparent',
              }}
            >
              <div style={{ fontSize: 14 }}>
                {p.raw_string} → {p.proposed_slug}
              </div>
              <div style={{ fontSize: 12, opacity: 0.7 }}>
                {p.proposed_parent_display_name ?? '(no parent)'}
              </div>
            </li>
          );
        })}
        {filtered.length === 0 && (
          <li style={{ padding: 12, fontStyle: 'italic', opacity: 0.6 }}>
            no proposals match this filter
          </li>
        )}
      </ul>
    </div>
  );
}
