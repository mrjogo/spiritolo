import { useState } from 'react';
import { FilterPopover, type FacetOption } from './FilterPopover';
import {
  setFilterValues,
  clearFilters,
  activeFilterCount,
  type RunFilterState,
  type MultiDimension,
} from './filter';
import type { Sort } from './useRunItems';

export interface FilterDimension {
  key: MultiDimension;
  label: string;
  options: FacetOption[];
}

export interface SortOption {
  col: string;
  label: string;
}

interface Props {
  state: RunFilterState;
  dimensions: FilterDimension[];
  sort: Sort;
  sortOptions: SortOption[];
  onChange: (state: RunFilterState) => void;
  onSortChange: (sort: Sort) => void;
}

// The JIRA-style filter bar: one popover button per dimension (label + active
// count badge), a sort control, and a free-text search — plus the row of
// active-filter pills joined by AND with a "Clear filters" reset. Selection
// lives outside this component, so re-filtering never clears it.
export function FilterBar({ state, dimensions, sort, sortOptions, onChange, onSortChange }: Props) {
  const [openDim, setOpenDim] = useState<MultiDimension | null>(null);

  const activePills = dimensions
    .filter((d) => state[d.key].length > 0)
    .map((d) => ({ key: d.key, label: d.label, values: state[d.key] }));
  const hasFilters = activeFilterCount(state) > 0;

  return (
    <>
      <div className="runs-filterbar">
        {dimensions.map((d) => {
          const count = state[d.key].length;
          return (
            <span key={d.key} style={{ position: 'relative' }}>
              <button
                type="button"
                className={`runs-fbtn${count > 0 ? ' is-active' : ''}`}
                aria-pressed={count > 0}
                aria-haspopup="dialog"
                onClick={() => setOpenDim(openDim === d.key ? null : d.key)}
              >
                {d.label}
                {count > 0 && <span className="runs-fbtn__b">{count}</span>}
                <span className="runs-caret" aria-hidden>▾</span>
              </button>
              {openDim === d.key && (
                <FilterPopover
                  title={d.label.toLowerCase()}
                  options={d.options}
                  selected={state[d.key]}
                  onApply={(values) => onChange(setFilterValues(state, d.key, values))}
                  onClose={() => setOpenDim(null)}
                />
              )}
            </span>
          );
        })}
        <button type="button" className="runs-fbtn is-dashed" disabled>
          ＋ Add filter
        </button>
        <span className="runs-grow" />
        <select
          aria-label="sort"
          value={`${sort.col}:${sort.asc ? 'asc' : 'desc'}`}
          onChange={(e) => {
            const [col, dir] = e.target.value.split(':');
            onSortChange({ col, asc: dir === 'asc' });
          }}
        >
          {sortOptions.flatMap((o) => [
            <option key={`${o.col}:desc`} value={`${o.col}:desc`}>Sort: {o.label} ↓</option>,
            <option key={`${o.col}:asc`} value={`${o.col}:asc`}>Sort: {o.label} ↑</option>,
          ])}
        </select>
        <input
          type="search"
          aria-label="search title or ingredient"
          placeholder="Search title / ingredient…"
          value={state.search ?? ''}
          onChange={(e) => onChange({ ...state, search: e.target.value })}
        />
      </div>

      {hasFilters && (
        <div className="runs-pills" role="group" aria-label="active filters">
          <span className="runs-plabel">Filters</span>
          {activePills.map((p, i) => (
            <span key={p.key} style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              {i > 0 && <span className="runs-and">AND</span>}
              <span className="runs-fpill">
                <b>{p.label}</b>: {p.values.join(', ')}
                <button
                  type="button"
                  className="runs-fpill__x"
                  aria-label={`Remove ${p.label} filter`}
                  onClick={() => onChange(setFilterValues(state, p.key, []))}
                >
                  ✕
                </button>
              </span>
            </span>
          ))}
          <button type="button" className="runs-clearall" onClick={() => onChange(clearFilters())}>
            Clear filters
          </button>
        </div>
      )}
    </>
  );
}
