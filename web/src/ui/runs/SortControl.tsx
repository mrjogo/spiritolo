import type { Sort } from './useRunItems';

export interface SortField {
  col: string;
  label: string;
}

interface Props {
  /** Ordered sort keys: first is primary, the rest are tiebreakers. */
  value: Sort[];
  fields: SortField[];
  onChange: (next: Sort[]) => void;
}

// A multidimensional sort builder: shows the ordered keys as chips
// ("Sort: Recipe ↑, then Source ↓"), each with a direction toggle and a remove
// button, plus an "add level" dropdown of the not-yet-used fields. Pairs with
// the RPCs' comma-separated multi-key sort (serializeSort).
export function SortControl({ value, fields, onChange }: Props) {
  const labelFor = (col: string) => fields.find((f) => f.col === col)?.label ?? col;
  const usedCols = new Set(value.map((k) => k.col));
  const available = fields.filter((f) => !usedCols.has(f.col));

  function toggleDir(i: number) {
    onChange(value.map((k, idx) => (idx === i ? { ...k, asc: !k.asc } : k)));
  }
  function remove(i: number) {
    onChange(value.filter((_, idx) => idx !== i));
  }
  function add(col: string) {
    if (col) onChange([...value, { col, asc: true }]);
  }

  return (
    <div className="runs-sortctl" role="group" aria-label="sort">
      {value.map((k, i) => (
        <span className="runs-sortkey" key={k.col}>
          <span className="runs-sortkey__lead">{i === 0 ? 'Sort:' : 'then'}</span>
          <span className="runs-sortkey__label">{labelFor(k.col)}</span>
          <button
            type="button"
            className="runs-sortkey__dir"
            aria-label={`toggle ${labelFor(k.col)} sort direction`}
            onClick={() => toggleDir(i)}
          >
            {k.asc ? '↑' : '↓'}
          </button>
          <button
            type="button"
            className="runs-sortkey__rm"
            aria-label={`remove ${labelFor(k.col)} sort`}
            onClick={() => remove(i)}
          >
            ✕
          </button>
        </span>
      ))}
      {available.length > 0 && (
        <select
          aria-label="add sort field"
          className="runs-sortadd"
          value=""
          onChange={(e) => add(e.target.value)}
        >
          <option value="">{value.length === 0 ? 'Sort by…' : '+ then by…'}</option>
          {available.map((f) => (
            <option key={f.col} value={f.col}>{f.label}</option>
          ))}
        </select>
      )}
    </div>
  );
}
