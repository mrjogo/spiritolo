import { useState } from 'react';
import { ModalShell } from '../Modal';
import { formatCents } from '../formatCents';
import type { RunHeader } from './useRun';
import type { LlmTier } from './llmTiers';
import { useEstimatedRunCents } from './useEstimate';

interface Props {
  run: RunHeader;
  tier: LlmTier;
  /** Default hard cap (dollars) prefilled into the input. */
  defaultCapDollars?: number;
  submitting?: boolean;
  error?: string | null;
  /** Providers a live worker can currently service (Start pre-flight). */
  workerProviders?: string[];
  /** True when no worker has reported recently. */
  workerStale?: boolean;
  onCancel: () => void;
  /** Fires with the hard cap in CENTS (start_run takes max_cost_cents). */
  onStart: (maxCostCents: number) => void;
}

const DEFAULT_CAP_DOLLARS = 1.5;

// The Start-run confirmation modal. Summarizes stage / task-count + composition
// / LLM tier / estimated cost, and takes a hard cost cap. There is deliberately
// NO acknowledge checkbox (per the approved mockup) — Start is enabled as soon
// as a valid positive cap is entered.
export function StartConfirmModal({
  run, tier, defaultCapDollars = DEFAULT_CAP_DOLLARS, submitting, error,
  workerProviders, workerStale, onCancel, onStart,
}: Props) {
  const [capInput, setCapInput] = useState(defaultCapDollars.toFixed(2));

  // Pre-flight: warn (don't block) if no worker is alive, or if none of the
  // live workers can service this run's provider — the run-#7 footgun where a
  // run was assembled for a provider the worker had no key for.
  const preflight = workerStale
    ? 'No worker is currently reporting — this run may sit queued until one starts.'
    : workerProviders && !workerProviders.includes(tier.provider)
      ? `No live worker can service "${tier.provider}" (available: ${workerProviders.join(', ') || 'none'}). The run will park until one can.`
      : null;

  const draftEstimate = useEstimatedRunCents(
    tier.provider, tier.model, run.task_count, run.cost_estimate_cents == null,
  );
  const estimateCents = run.cost_estimate_cents ?? draftEstimate;
  const capDollars = Number.parseFloat(capInput);
  const capValid = Number.isFinite(capDollars) && capDollars > 0;
  const startEnabled = capValid && !submitting;

  const composition = [
    run.flagged_count ? `${run.flagged_count.toLocaleString()} flagged` : null,
    run.never_run_count ? `${run.never_run_count.toLocaleString()} never run` : null,
    run.failed_count ? `${run.failed_count.toLocaleString()} retry failed` : null,
  ].filter(Boolean).join(' · ');

  return (
    <ModalShell onBackdropClick={onCancel}>
      <h2 className="tx-modal__title">Start run #{run.id}?</h2>
      <div className="runs-modal__sub">The worker will begin processing immediately once approved.</div>

      <div className="runs-modal__row">
        <span className="k">Stage</span>
        <span className="v">{run.stage}</span>
      </div>
      <div className="runs-modal__row">
        <span className="k">Tasks</span>
        <span className="v">
          {run.task_count.toLocaleString()}
          {composition && <span className="runs-modal__comp"> · {composition}</span>}
        </span>
      </div>
      <div className="runs-modal__row">
        <span className="k">LLM tier</span>
        <span className="v">
          {tier.shortLabel}{' '}
          <span className="runs-modal__comp">{tier.metered ? 'metered' : 'free'}</span>
        </span>
      </div>

      <div className="runs-estbox">
        <div>
          <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.4px', color: 'var(--runs-amber)', fontWeight: 600 }}>
            Estimated cost
          </div>
          <div className="runs-estbox__amt">≈ {formatCents(estimateCents)}</div>
        </div>
        {tier.metered && <span className="runs-tag">metered</span>}
      </div>

      <div className="runs-capline">
        <label htmlFor="runs-hard-cap">Hard cost cap</label>
        <input
          id="runs-hard-cap"
          aria-label="hard cost cap dollars"
          type="number"
          min={0}
          step="0.01"
          value={capInput}
          onChange={(e) => setCapInput(e.target.value)}
        />
        <span className="runs-modal__sub" style={{ margin: 0 }}>stop the run if it exceeds this</span>
      </div>

      {preflight && <div className="runs-preflight">⚠ {preflight}</div>}

      {error && <div className="tx-field__error">{error}</div>}

      <div className="tx-form-actions">
        <button type="button" onClick={onCancel} disabled={submitting}>
          Cancel
        </button>
        <button
          type="button"
          className="runs-btn--primary"
          disabled={!startEnabled}
          onClick={() => onStart(Math.round(capDollars * 100))}
        >
          Start run →
        </button>
      </div>
    </ModalShell>
  );
}
