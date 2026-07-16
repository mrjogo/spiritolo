import { useState } from 'react';

// Hand-rolled, read-only, collapsible JSON pretty-printer — no external
// lib (no react-json-view). Used for doc/jsonld/bundle previews across
// /ops: the docs browser, audit before/after diff, and the exports preview.
interface Props {
  value: unknown;
  name?: string;
  depth?: number;
  /** Nodes at this depth or deeper start collapsed. Default 1 — the root
   *  renders expanded so there's something to see; its children start
   *  collapsed. */
  collapseAtDepth?: number;
}

export function JsonView({ value, name, depth = 0, collapseAtDepth = 1 }: Props) {
  if (value === null || typeof value !== 'object') {
    return <Leaf name={name} value={value} />;
  }
  const isArray = Array.isArray(value);
  const entries: [string, unknown][] = isArray
    ? (value as unknown[]).map((v, i) => [String(i), v])
    : Object.entries(value as Record<string, unknown>);
  return (
    <ExpandableNode
      name={name}
      entries={entries}
      isArray={isArray}
      depth={depth}
      collapseAtDepth={collapseAtDepth}
    />
  );
}

function Leaf({ name, value }: { name?: string; value: unknown }) {
  return (
    <div className="json-view__leaf">
      {name !== undefined && <span className="json-view__key">{name}: </span>}
      <span className="json-view__value">{JSON.stringify(value)}</span>
    </div>
  );
}

function ExpandableNode({
  name, entries, isArray, depth, collapseAtDepth,
}: {
  name?: string;
  entries: [string, unknown][];
  isArray: boolean;
  depth: number;
  collapseAtDepth: number;
}) {
  const [expanded, setExpanded] = useState(depth < collapseAtDepth);
  const summary = isArray ? `Array(${entries.length})` : `Object(${entries.length})`;
  return (
    <div className="json-view__node">
      <button
        type="button"
        aria-expanded={expanded}
        aria-label={name !== undefined ? `toggle ${name}` : 'toggle'}
        onClick={() => setExpanded((e) => !e)}
        className="json-view__toggle"
        style={{
          background: 'transparent', border: 'none', cursor: 'pointer',
          font: 'inherit', padding: 0, display: 'inline-flex', gap: 4,
        }}
      >
        <span aria-hidden>{expanded ? '▾' : '▸'}</span>
        {name !== undefined && <span className="json-view__key">{name}:</span>}
        <span className="json-view__summary">{summary}</span>
      </button>
      {expanded && (
        <div className="json-view__children" style={{ paddingLeft: 16 }}>
          {entries.map(([k, v]) => (
            <JsonView key={k} name={k} value={v} depth={depth + 1} collapseAtDepth={collapseAtDepth} />
          ))}
        </div>
      )}
    </div>
  );
}
