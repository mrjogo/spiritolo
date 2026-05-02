import { TX_BROWN_MID, TX_CREAM_RGBA, TX_FRAME_EDGE, TX_GOLD, TX_NODE_BG } from './palette';
import type { FilterKey } from './shapeData';

export type { FilterKey };

const ORDERED: FilterKey[] = [
  'substance', 'expression', 'brand',
  'cluster', 'orphan', 'no aliases', 'zero recipes',
];

const LABELS: Record<FilterKey, string> = {
  substance: 'substance',
  expression: 'expression',
  brand: 'brand',
  cluster: 'clustering node',
  orphan: 'orphan',
  'no aliases': 'no aliases',
  'zero recipes': 'zero recipes',
};

interface Props {
  active: Set<FilterKey>;
  onToggle: (key: FilterKey) => void;
}

export function FilterChips({ active, onToggle }: Props) {
  return (
    <div
      role="group"
      aria-label="Filter nodes by role and flag"
      style={{
        display: 'flex', flexWrap: 'wrap', gap: 4, maxWidth: 240,
      }}
    >
      {ORDERED.map((key) => {
        const isActive = active.has(key);
        return (
          <button
            key={key}
            type="button"
            aria-pressed={isActive}
            onClick={() => onToggle(key)}
            style={{
              fontFamily: "'Cinzel', serif",
              fontSize: 11, letterSpacing: '0.2em',
              padding: '4px 10px',
              borderRadius: 12,
              border: `1px solid ${TX_FRAME_EDGE}`,
              background: isActive ? TX_GOLD : TX_CREAM_RGBA,
              color: isActive ? TX_NODE_BG : TX_BROWN_MID,
              cursor: 'pointer',
              textTransform: 'uppercase',
            }}
          >
            {LABELS[key]}
          </button>
        );
      })}
    </div>
  );
}
