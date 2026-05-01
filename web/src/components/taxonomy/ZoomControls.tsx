import type { CSSProperties } from 'react';
import { TX_BROWN_MID, TX_FRAME_EDGE } from './palette';

interface Props {
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
}

export function ZoomControls({ onZoomIn, onZoomOut, onFit }: Props) {
  return (
    <div
      className="tx-card"
      style={{
        position: 'absolute', bottom: 24, right: 24, zIndex: 3,
        padding: 0, display: 'flex',
        fontFamily: "'Cinzel', serif", fontSize: 13,
      }}
    >
      <button type="button" aria-label="Zoom out" onClick={onZoomOut} style={btn(true)}>−</button>
      <button type="button" aria-label="Zoom in" onClick={onZoomIn} style={btn(true)}>+</button>
      <button type="button" aria-label="Fit to view" onClick={onFit} style={btn(false)}>⊡</button>
    </div>
  );
}

function btn(borderRight: boolean): CSSProperties {
  return {
    background: 'transparent',
    border: 'none',
    padding: '6px 10px',
    cursor: 'pointer',
    color: TX_BROWN_MID,
    borderRight: borderRight ? `1px solid ${TX_FRAME_EDGE}` : 'none',
    fontFamily: 'inherit',
    fontSize: 'inherit',
  };
}
