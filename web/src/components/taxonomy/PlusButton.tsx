interface Props {
  x: number;          // viewport pixel x of node center
  y: number;          // viewport pixel y of node center
  radius: number;     // node radius in viewport pixels
  onClick: () => void;
  ariaLabel: string;
}

export function PlusButton({ x, y, radius, onClick, ariaLabel }: Props) {
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      onClick={onClick}
      style={{
        position: 'absolute',
        left: x + radius * 0.7 - 9,
        top: y - radius * 0.7 - 9,
        width: 18, height: 18, borderRadius: 9,
        background: '#f8f0d8',
        border: '1px solid #8b6f3a',
        color: '#5a4220',
        cursor: 'pointer',
        font: 'bold 14px sans-serif', lineHeight: '14px',
        padding: 0,
        zIndex: 5,
        boxShadow: '0 2px 4px rgba(0,0,0,0.3)',
      }}
    >+</button>
  );
}
