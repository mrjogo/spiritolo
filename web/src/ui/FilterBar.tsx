import { useState } from 'react';
import { FilterChips, type ChipOption } from '../components/taxonomy/FilterChips';
import type { PostgrestFilter } from './hooks/usePagedQuery';

export interface ScopeDescriptor {
  kind: 'filter';
  stage?: string;
  site?: string;
  limit?: number;
  where?: PostgrestFilter[];
}

export interface FilterBarValue {
  filters: PostgrestFilter[];
  scope: ScopeDescriptor;
}

interface Props {
  /** The pipeline stage this bar's scope descriptor is for (used by a
   *  TriggerBar acting on the same filtered set — not consulted here). */
  stage?: string;
  siteOptions?: string[];
  chipOptions?: ChipOption[];
  onChange: (value: FilterBarValue) => void;
}

// site <select> + free-text + outcome/confidence/state chips (reusing
// taxonomy/FilterChips with a different chip vocabulary), emitting ONE
// {filters, scope} object per change. The load-bearing property: scope.where
// IS the same array as filters — what usePagedQuery renders and what
// enqueue_job would act on can never drift apart because they're the same
// reference, not two independently-derived copies.
export function FilterBar({ stage, siteOptions = [], chipOptions = [], onChange }: Props) {
  const [site, setSite] = useState('');
  const [text, setText] = useState('');
  const [active, setActive] = useState<Set<string>>(new Set());

  function emit(nextSite: string, nextText: string, nextActive: Set<string>) {
    const filters: PostgrestFilter[] = [];
    if (nextSite) filters.push({ col: 'site', op: 'eq', value: nextSite });
    if (nextText) filters.push({ col: 'name', op: 'ilike', value: `%${nextText}%` });
    for (const key of nextActive) {
      filters.push({ col: 'outcome', op: 'eq', value: key });
    }
    onChange({
      filters,
      scope: { kind: 'filter', stage, site: nextSite || undefined, where: filters },
    });
  }

  return (
    <div className="filter-bar" style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
      <select
        aria-label="site"
        value={site}
        onChange={(e) => {
          setSite(e.target.value);
          emit(e.target.value, text, active);
        }}
      >
        <option value="">All sites</option>
        {siteOptions.map((s) => (
          <option key={s} value={s}>{s}</option>
        ))}
      </select>
      <input
        type="search"
        aria-label="filter text"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          emit(site, e.target.value, active);
        }}
      />
      <FilterChips<string>
        active={active}
        groupLabel="Filter results"
        options={chipOptions}
        onToggle={(key) => {
          setActive((prev) => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key); else next.add(key);
            emit(site, text, next);
            return next;
          });
        }}
      />
    </div>
  );
}
