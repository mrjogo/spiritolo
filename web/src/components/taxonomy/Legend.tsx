import { ROLE_FILL, TX_CLUSTER_RING, TX_FRAME_EDGE } from './palette';

export function Legend() {
  return (
    <div
      className="tx-card"
      style={{
        padding: '8px 12px', fontSize: 13, lineHeight: 1.6, width: 180,
      }}
    >
      <div className="tx-card__heading" style={{ marginBottom: 4 }}>LEGEND</div>
      <LegendDot color={ROLE_FILL.substance} /> substance<br />
      <LegendDot color={ROLE_FILL.expression} /> expression<br />
      <LegendDot color={ROLE_FILL.brand} /> brand<br />
      <LegendDot color={ROLE_FILL.unknown} /> node kind not set<br />
      <LegendRing color={TX_CLUSTER_RING} /> clustering ring
    </div>
  );
}

const SWATCH_DIAMETER = 9;

function LegendDot({ color }: { color: string }) {
  return (
    <span
      style={{
        display: 'inline-block', width: SWATCH_DIAMETER, height: SWATCH_DIAMETER,
        borderRadius: '50%', boxSizing: 'border-box',
        background: color, border: `1px solid ${TX_FRAME_EDGE}`,
        verticalAlign: 'middle', marginRight: 6,
      }}
    />
  );
}

function LegendRing({ color }: { color: string }) {
  return (
    <span
      style={{
        display: 'inline-block', width: SWATCH_DIAMETER, height: SWATCH_DIAMETER,
        borderRadius: '50%', boxSizing: 'border-box',
        background: 'transparent', border: `2px solid ${color}`,
        verticalAlign: 'middle', marginRight: 6,
      }}
    />
  );
}
