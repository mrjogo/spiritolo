interface Props {
  x: number;
  y: number;
  radius: number;
}

export function HighlightPulse({ x, y, radius }: Props) {
  const size = (radius + 8) * 2;
  return (
    <div
      aria-hidden
      className="tx-highlight-pulse"
      style={{
        position: 'absolute',
        left: x - size / 2, top: y - size / 2,
        width: size, height: size,
        pointerEvents: 'none',
        zIndex: 4,
      }}
    />
  );
}
