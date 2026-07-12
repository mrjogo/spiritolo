// stage_run outcomes ∪ job states — the two closed vocabularies /ops renders
// as pills. Anything else falls back to a neutral pill (never throws) so a
// future outcome/state value doesn't crash the dashboard.
const LABELS: Record<string, string> = {
  resolved: 'resolved',
  abstain: 'abstain',
  pending: 'pending',
  failed: 'failed',
  proposes_new: 'proposes new',
  queued: 'queued',
  claimed: 'claimed',
  running: 'running',
  done: 'done',
  succeeded: 'succeeded',
  error: 'error',
};

const TOKEN_VARS: Record<string, string> = {
  resolved: '--st-resolved',
  abstain: '--st-abstain',
  pending: '--st-pending',
  failed: '--st-failed',
  proposes_new: '--st-proposes-new',
  queued: '--job-queued',
  claimed: '--job-queued',
  running: '--job-running',
  done: '--job-done',
  succeeded: '--job-done',
  error: '--job-error',
};

const NEUTRAL_VAR = '--ops-muted';

interface Props {
  kind: string;
}

export function StatusPill({ kind }: Props) {
  const colorVar = TOKEN_VARS[kind] ?? NEUTRAL_VAR;
  const label = LABELS[kind] ?? kind;
  return (
    <span
      className={`status-pill status-pill--${TOKEN_VARS[kind] ? kind.replace(/_/g, '-') : 'neutral'}`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '2px 8px',
        borderRadius: 999,
        fontSize: 11,
        fontFamily: 'ui-monospace, monospace',
        letterSpacing: '0.04em',
        color: `var(${colorVar})`,
        border: `1px solid var(${colorVar})`,
      }}
    >
      {label}
    </span>
  );
}
