import { TX_GOLD, TX_NODE_BG } from './palette';

interface Props {
  x: number;          // viewport pixel x of node center
  y: number;          // viewport pixel y of node center
  radius: number;     // node OUTER ring radius in on-screen pixels (zoom-applied)
  onClick: () => void;
  ariaLabel: string;
}

// Hairline gold ring with thin "+" cross at 45° upper-right of the node.
// Both the ring size and the edge-to-edge gap scale freely with the
// on-screen node radius so the composition stays in proportion across
// the full zoom range — bigger node, bigger "+". The parent (Taxonomy)
// is responsible for hiding the button at faraway zoom levels where it
// would shrink to nothing; here we trust the radius we're given.
const RING_RATIO = 0.4;     // plus ring radius / node outer radius
const GAP_RATIO  = 0.2;     // gap / node outer radius
const HALF_INV_SQRT2 = 1 / Math.SQRT2; // ≈ 0.7071

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v));
}

export function PlusButton({ x, y, radius, onClick, ariaLabel }: Props) {
  const ringR = radius * RING_RATIO;
  const gap = radius * GAP_RATIO;
  const centerToCenter = radius + gap + ringR;
  const offset = centerToCenter * HALF_INV_SQRT2;
  const cx = x + offset;
  const cy = y - offset;
  const size = ringR * 2;
  // Stroke targets ~1 screen pixel regardless of ring size: strokeWidth is
  // in viewBox units and 1 viewBox unit = (size / 14) screen pixels, so
  // 14 / size lands at ~1 screen px. Clamp prevents the stroke from
  // hitting zero (invisible) at huge ring sizes or blowing out the
  // viewBox at very small ring sizes.
  const stroke = clamp(14 / size, 0.6, 1.4);
  // Inner radius shrunk from 6.5 → 6 so the stroke (centered on r) has
  // room to extend outward without falling outside the 0..14 viewBox.
  const ringSvgR = 6;

  return (
    <button
      type="button"
      aria-label={ariaLabel}
      onClick={onClick}
      style={{
        position: 'absolute',
        left: cx - ringR,
        top: cy - ringR,
        width: size, height: size,
        padding: 0,
        background: 'transparent',
        border: 'none',
        cursor: 'pointer',
        zIndex: 5,
      }}
    >
      <svg width={size} height={size} viewBox="0 0 14 14" aria-hidden>
        <circle cx="7" cy="7" r={ringSvgR} fill={TX_NODE_BG} stroke={TX_GOLD} strokeWidth={stroke} />
        <line x1="4" y1="7" x2="10" y2="7" stroke={TX_GOLD} strokeWidth={stroke} />
        <line x1="7" y1="4" x2="7" y2="10" stroke={TX_GOLD} strokeWidth={stroke} />
      </svg>
    </button>
  );
}
