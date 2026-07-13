import { useState } from 'react';
import { ModalShell } from './Modal';
import { CostBadge } from './CostBadge';
import { useRpc } from './hooks/useRpc';
import type { ScopeDescriptor } from './scope';

// A type alias (not an interface) so it structurally satisfies useRpc's
// `Record<string, unknown>` generic constraint — interfaces don't get an
// implicit index signature from TypeScript the way object-literal type
// aliases do, even when every property is index-signature-compatible.
type EnqueueArgs = {
  p_stage: string;
  p_kind: string;
  p_payload: { scope: ScopeDescriptor };
  p_version: string | null;
  p_requires_approval: boolean;
  p_cost_estimate_cents: number | null;
  p_max_cost_cents: number;
};

interface Props {
  stage: string;
  scope: ScopeDescriptor;
  version?: string;
  /** Known item count for the estimate; omitted when the scope's size isn't
   *  knowable yet (e.g. whole_queue with no queue-depth surface) — shown as
   *  a placeholder rather than guessed. */
  itemCount?: number;
  /** Naive per-item cost heuristic for the displayed estimate — a stand-in
   *  for a real worker-computed estimate_job_cost RPC. */
  estimatedCentsPerItem?: number;
  onCancel: () => void;
  onConfirmed: (jobId: number) => void;
}

const DEFAULT_CENTS_PER_ITEM = 1;

export function CostConfirmModal({
  stage, scope, version, itemCount, estimatedCentsPerItem = DEFAULT_CENTS_PER_ITEM,
  onCancel, onConfirmed,
}: Props) {
  const [acknowledged, setAcknowledged] = useState(false);
  const [maxCostInput, setMaxCostInput] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const enqueue = useRpc<EnqueueArgs, number>('enqueue_job', { invalidate: [['jobs']] });
  const approve = useRpc<{ p_id: number }, void>('approve_job', { invalidate: [['jobs']] });

  const estimateCents = itemCount != null ? itemCount * estimatedCentsPerItem : null;
  const maxCostCents = Number.parseInt(maxCostInput, 10);
  const maxCostValid = maxCostInput !== '' && Number.isFinite(maxCostCents) && maxCostCents > 0;
  const confirmEnabled = acknowledged && maxCostValid && !submitting;

  async function handleConfirm() {
    setSubmitting(true);
    setError(null);
    try {
      const jobId = await enqueue.mutateAsync({
        p_stage: stage,
        p_kind: 'run',
        p_payload: { scope },
        p_version: version ?? null,
        p_requires_approval: true,
        p_cost_estimate_cents: estimateCents,
        p_max_cost_cents: maxCostCents,
      });
      await approve.mutateAsync({ p_id: jobId });
      onConfirmed(jobId);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalShell onBackdropClick={onCancel}>
      <h2 className="tx-modal__title">Confirm metered run — {stage}</h2>

      <div className="tx-field">
        <div className="tx-field__label">Items</div>
        <div>{itemCount ?? '—'}</div>
      </div>

      <div className="tx-field">
        <div className="tx-field__label">Estimated cost</div>
        <CostBadge cents={estimateCents} metered variant="est" />
      </div>

      <div className="tx-field">
        <label className="tx-field__label" htmlFor="cost-confirm-max">Max cost (cents)</label>
        <input
          id="cost-confirm-max"
          className="tx-input"
          aria-label="max cost cents"
          type="number"
          min={1}
          value={maxCostInput}
          onChange={(e) => setMaxCostInput(e.target.value)}
        />
      </div>

      <label className="tx-field" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input
          type="checkbox"
          aria-label="acknowledge estimated cost"
          checked={acknowledged}
          onChange={(e) => setAcknowledged(e.target.checked)}
        />
        I acknowledge this run may incur the estimated cost
      </label>

      {error && <div className="tx-field__error">{error}</div>}

      <div className="tx-form-actions">
        <button type="button" className="tx-btn tx-btn--ghost" onClick={onCancel} disabled={submitting}>
          Cancel
        </button>
        <button
          type="button"
          className="tx-btn"
          disabled={!confirmEnabled}
          onClick={handleConfirm}
        >
          Confirm
        </button>
      </div>
    </ModalShell>
  );
}
