import { TX_BROWN_MID, TX_FRAME_EDGE } from './palette';

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
}

export function SearchBox({ value, onChange, onSubmit }: Props) {
  return (
    <div
      className="tx-card"
      style={{
        position: 'absolute', top: 14, left: 14, zIndex: 3,
        padding: '8px 12px', width: 180,
      }}
    >
      <div className="tx-card__heading" style={{ marginBottom: 4 }}>SEARCH</div>
      <input
        type="text"
        value={value}
        placeholder="rye, vermouth, …"
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') onSubmit(); }}
        style={{
          width: '100%', background: 'transparent', border: 'none',
          borderBottom: `1px solid ${TX_FRAME_EDGE}`, outline: 'none',
          fontFamily: "'Cormorant Garamond', Georgia, serif",
          fontStyle: 'italic', fontSize: 14, color: TX_BROWN_MID, padding: '2px 0',
        }}
      />
    </div>
  );
}
