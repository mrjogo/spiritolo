import { useState } from 'react';
import { flagReview } from '../../reviews/flagReview';
import { useIsAdmin } from '../../auth/useIsAdmin';

interface Props {
  entityKind: string;
  entityId: string;
  stage: string;
}

// Admin-only affordance to flag a pipeline entity for human review at a given
// stage. Renders nothing for non-admins. On success it collapses into a
// subtle, non-interactive "Flagged" marker so the same row can't be
// double-flagged from the UI.
export function FlagButton({ entityKind, entityId, stage }: Props) {
  const { isAdmin } = useIsAdmin();
  const [flagged, setFlagged] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!isAdmin) return null;

  if (flagged) {
    return (
      <span
        aria-label="flagged"
        style={{ fontSize: 11, opacity: 0.7, fontStyle: 'italic' }}
      >
        flagged
      </span>
    );
  }

  async function handleClick() {
    if (busy) return;
    setBusy(true);
    try {
      await flagReview({ entityKind, entityId, stage });
      setFlagged(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={busy}
      style={{
        fontSize: 11,
        padding: '2px 6px',
        borderRadius: 4,
        border: '1px solid var(--ops-border, #e3e5e9)',
        background: 'transparent',
        cursor: busy ? 'default' : 'pointer',
        opacity: busy ? 0.6 : 1,
      }}
    >
      Flag
    </button>
  );
}
