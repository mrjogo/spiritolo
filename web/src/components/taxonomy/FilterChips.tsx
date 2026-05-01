import { TX_FRAME_EDGE, TX_GOLD, TX_NODE_BG, TX_BROWN_MID } from './palette';

export type FilterKey =
  | 'substance' | 'expression' | 'brand'
  | 'cluster' | 'orphan' | 'no aliases' | 'zero recipes';

const ORDERED: FilterKey[] = [
  'substance', 'expression', 'brand',
  'cluster', 'orphan', 'no aliases', 'zero recipes',
];

interface Props {
  active: Set<FilterKey>;
  onToggle: (key: FilterKey) => void;
}

export function FilterChips({ active, onToggle }: Props) {
  return (
    <div
      style={{
        position: 'absolute', top: 70, left: 14, zIndex: 3,
        display: 'flex', flexWrap: 'wrap', gap: 4, maxWidth: 220,
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
              fontSize: 9, letterSpacing: '0.2em',
              padding: '3px 8px',
              borderRadius: 10,
              border: `1px solid ${TX_FRAME_EDGE}`,
              background: isActive ? TX_GOLD : 'rgba(245, 233, 200, 0.85)',
              color: isActive ? TX_NODE_BG : TX_BROWN_MID,
              cursor: 'pointer',
              textTransform: 'uppercase',
            }}
          >
            {key}
          </button>
        );
      })}
    </div>
  );
}
