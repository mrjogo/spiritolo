import type { Candidate } from './schemas';

interface Props {
  candidates: Candidate[];
  onPick: (nodeId: number) => void;
}

export function CandidatesList({ candidates, onPick }: Props) {
  if (candidates.length === 0) {
    return (
      <div style={{ fontStyle: 'italic', opacity: 0.6, fontSize: 13 }}>
        no candidates suggested
      </div>
    );
  }
  return (
    <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
      {candidates.map((c) => (
        <li key={c.node_id}>
          <button
            type="button"
            onClick={() => onPick(c.node_id)}
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              width: '100%',
              padding: '6px 10px',
              background: 'transparent',
              border: '1px solid var(--tx-form-border)',
              borderRadius: 'var(--tx-form-radius)',
              marginBottom: 4,
              cursor: 'pointer',
              fontFamily: 'inherit',
              color: 'inherit',
              textAlign: 'left',
            }}
          >
            <span>{c.display_name}</span>
            <span style={{ opacity: 0.7, fontVariantNumeric: 'tabular-nums' }}>
              {c.similarity.toFixed(2)}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
