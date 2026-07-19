import { useState } from 'react';

export interface FacetOption {
  value: string;
  label: string;
  count: number;
}

interface Props {
  title: string;
  options: FacetOption[];
  selected: string[];
  onApply: (values: string[]) => void;
  onClose: () => void;
}

// A JIRA-style multi-select popover: a filterable list of every option with
// its facet count, checkbox-toggled into a local draft, committed on Apply.
// OR-within-a-dimension — checking two values matches either.
export function FilterPopover({ title, options, selected, onApply, onClose }: Props) {
  const [draft, setDraft] = useState<Set<string>>(new Set(selected));
  const [query, setQuery] = useState('');

  const shown = options.filter((o) => o.label.toLowerCase().includes(query.trim().toLowerCase()));

  function toggle(value: string) {
    setDraft((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  }

  return (
    <div className="runs-popover" role="dialog" aria-label={`Filter: ${title}`}>
      <div className="runs-popover__h">Filter: {title}</div>
      <div className="runs-popover__search">
        <input
          type="text"
          aria-label={`Find a ${title}`}
          placeholder={`Find a ${title}…`}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      {shown.map((o) => (
        <label className="runs-opt" key={o.value}>
          <input
            type="checkbox"
            aria-label={o.label}
            checked={draft.has(o.value)}
            onChange={() => toggle(o.value)}
          />
          {o.label}
          <span className="runs-opt__cnt">{o.count.toLocaleString()}</span>
        </label>
      ))}
      <div className="runs-pfoot">
        <button type="button" className="runs-clearall" onClick={() => setDraft(new Set())}>
          Clear
        </button>
        <button
          type="button"
          className="runs-btn--primary"
          onClick={() => {
            onApply([...draft]);
            onClose();
          }}
        >
          Apply
        </button>
      </div>
    </div>
  );
}
