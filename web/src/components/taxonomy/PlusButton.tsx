import { TX_GOLD, TX_NODE_BG } from './palette';

interface Props {
  x: number;          // viewport pixel x of node center
  y: number;          // viewport pixel y of node center
  radius: number;     // node radius in viewport pixels
  onClick: () => void;
  ariaLabel: string;
}

// Hairline gold ring with thin "+" cross. Sits at 45° upper-right of the
// node, with an 8 px edge-to-edge gap that stays constant as the node
// scales. dx = dy = (r_node + 8 + R_plus) / √2 puts the plus center on
// the diagonal at exactly the right distance.
const GAP_PX = 8;
const RING_RADIUS = 7;
const HALF_INV_SQRT2 = 1 / Math.SQRT2; // ≈ 0.7071

export function PlusButton({ x, y, radius, onClick, ariaLabel }: Props) {
  const centerToCenter = radius + GAP_PX + RING_RADIUS;
  const offset = centerToCenter * HALF_INV_SQRT2;
  const cx = x + offset;
  const cy = y - offset;
  const size = RING_RADIUS * 2; // 14 px

  return (
    <button
      type="button"
      aria-label={ariaLabel}
      onClick={onClick}
      style={{
        position: 'absolute',
        left: cx - RING_RADIUS,
        top: cy - RING_RADIUS,
        width: size, height: size,
        padding: 0,
        background: 'transparent',
        border: 'none',
        cursor: 'pointer',
        zIndex: 5,
      }}
    >
      <svg width={size} height={size} viewBox="0 0 14 14" aria-hidden>
        <circle cx="7" cy="7" r="6.5" fill={TX_NODE_BG} stroke={TX_GOLD} strokeWidth="0.8" />
        <line x1="3.5" y1="7" x2="10.5" y2="7" stroke={TX_GOLD} strokeWidth="0.8" />
        <line x1="7" y1="3.5" x2="7" y2="10.5" stroke={TX_GOLD} strokeWidth="0.8" />
      </svg>
    </button>
  );
}
