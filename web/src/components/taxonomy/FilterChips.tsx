import { TX_BROWN_MID, TX_CREAM_RGBA, TX_FRAME_EDGE, TX_GOLD, TX_NODE_BG } from './palette';
import type { FilterKey } from './shapeData';

export type { FilterKey };

export interface ChipOption<K = string> {
  key: K;
  label: string;
}

const DEFAULT_ORDERED: FilterKey[] = [
  'substance', 'expression', 'brand',
  'cluster', 'orphan', 'no aliases', 'zero recipes',
];

const DEFAULT_LABELS: Record<FilterKey, string> = {
  substance: 'substance',
  expression: 'expression',
  brand: 'brand',
  cluster: 'clustering node',
  orphan: 'orphan',
  'no aliases': 'no aliases',
  'zero recipes': 'zero recipes',
};

const DEFAULT_OPTIONS: ChipOption<FilterKey>[] = DEFAULT_ORDERED.map((key) => ({
  key,
  label: DEFAULT_LABELS[key],
}));

interface Props<K = FilterKey> {
  active: Set<K>;
  onToggle: (key: K) => void;
  /** Defaults to the taxonomy role/flag chip set. Pass a different set to
   *  reuse this component for a different chip vocabulary (e.g. FilterBar's
   *  outcome/confidence/state chips in /ops) without touching the taxonomy
   *  default. */
  options?: ChipOption<K>[];
  groupLabel?: string;
}

export function FilterChips<K = FilterKey>({
  active, onToggle, options, groupLabel = 'Filter nodes by role and flag',
}: Props<K>) {
  const opts = options ?? (DEFAULT_OPTIONS as unknown as ChipOption<K>[]);
  return (
    <div
      role="group"
      aria-label={groupLabel}
      style={{
        display: 'flex', flexWrap: 'wrap', gap: 4, maxWidth: 240,
      }}
    >
      {opts.map(({ key, label }) => {
        const isActive = active.has(key);
        return (
          <button
            key={String(key)}
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
            {label}
          </button>
        );
      })}
    </div>
  );
}
