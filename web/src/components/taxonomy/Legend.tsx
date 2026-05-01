import { ROLE_FILL, TX_BROWN_SOFT, TX_FRAME_EDGE } from './palette';

export function Legend() {
  return (
    <div
      className="tx-card"
      style={{
        position: 'absolute', top: 14, right: 14, zIndex: 2,
        padding: '8px 12px', fontSize: 12, lineHeight: 1.55, width: 160,
      }}
    >
      <div className="tx-card__heading" style={{ marginBottom: 4 }}>LEGEND</div>
      <LegendDot color={ROLE_FILL.substance} /> substance<br />
      <LegendDot color={ROLE_FILL.expression} /> expression<br />
      <LegendDot color={ROLE_FILL.brand} /> brand<br />
      <div style={{ marginTop: 4, fontStyle: 'italic', color: TX_BROWN_SOFT, lineHeight: 1.4 }}>
        ◯ ring = cluster · ⌀ dashed = orphan<br />
        ? = role inferred · ❦ = defining garnish
      </div>
    </div>
  );
}

function LegendDot({ color }: { color: string }) {
  return (
    <span
      style={{
        display: 'inline-block', width: 9, height: 9, borderRadius: '50%',
        background: color, border: `1px solid ${TX_FRAME_EDGE}`, verticalAlign: 'middle',
        marginRight: 6,
      }}
    />
  );
}
