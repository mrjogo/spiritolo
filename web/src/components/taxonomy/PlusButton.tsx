import { TX_GOLD, TX_NODE_BG } from './palette';

interface Props {
  x: number;          // viewport pixel x of node center
  y: number;          // viewport pixel y of node center
  radius: number;     // node OUTER ring radius in on-screen pixels (zoom-applied)
  onClick: () => void;
  ariaLabel: string;
}

// Hairline gold ring with thin "+" cross at 45° upper-right of the node.
// Both the ring size and the edge-to-edge gap scale with the on-screen
// node radius so the composition stays in proportion at every zoom level,
// clamped to a usable [min, max] range so it stays clickable when tiny
// and stays a UI affordance instead of wallpaper when huge.
const RING_RATIO = 0.4;     // plus ring radius / node outer radius
const GAP_RATIO  = 0.2;     // gap / node outer radius
const MIN_RING = 5;
const MAX_RING = 20;
const MIN_GAP = 4;
const MAX_GAP = 12;
const HALF_INV_SQRT2 = 1 / Math.SQRT2; // ≈ 0.7071

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v));
}

export function PlusButton({ x, y, radius, onClick, ariaLabel }: Props) {
  const ringR = clamp(radius * RING_RATIO, MIN_RING, MAX_RING);
  const gap = clamp(radius * GAP_RATIO, MIN_GAP, MAX_GAP);
  const centerToCenter = radius + gap + ringR;
  const offset = centerToCenter * HALF_INV_SQRT2;
  const cx = x + offset;
  const cy = y - offset;
  const size = ringR * 2;
  // Stroke widths scale gently — keep the design "hairline" everywhere
  // by deriving stroke from the ring size, with a floor so it doesn't
  // disappear at min ring.
  const stroke = Math.max(0.7, ringR * 0.11);

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
        <circle cx="7" cy="7" r="6.5" fill={TX_NODE_BG} stroke={TX_GOLD} strokeWidth={stroke} />
        <line x1="3.5" y1="7" x2="10.5" y2="7" stroke={TX_GOLD} strokeWidth={stroke} />
        <line x1="7" y1="3.5" x2="7" y2="10.5" stroke={TX_GOLD} strokeWidth={stroke} />
      </svg>
    </button>
  );
}
