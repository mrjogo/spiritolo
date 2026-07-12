import { formatCents } from './formatCents';

interface Props {
  cents: number | null | undefined;
  /** Adds a coin glyph + amber tint — this cost came from a metered stage. */
  metered?: boolean;
  /** Distinguishes an estimate (pre-approval) from the actual charge. */
  variant?: 'est' | 'actual';
}

export function CostBadge({ cents, metered = false, variant }: Props) {
  return (
    <span
      className={metered ? 'cost-badge cost-badge--metered' : 'cost-badge'}
      aria-label={variant ? `${variant} cost` : 'cost'}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        fontFamily: 'ui-monospace, monospace',
        fontSize: 12,
        color: metered ? '#a06a00' : 'inherit',
      }}
    >
      {metered && (
        <span aria-hidden className="cost-badge__coin">
          🪙
        </span>
      )}
      {variant && <span className="cost-badge__label">{variant}</span>}
      <span className="cost-badge__amount">{formatCents(cents)}</span>
    </span>
  );
}
