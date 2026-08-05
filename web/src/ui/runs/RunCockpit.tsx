import { formatCents } from '../formatCents';
import { bucketSeconds } from './bucketSeconds';
import { useEstimatedRunSeconds } from './useEstimateSeconds';
import { useWorkerHealth } from './useWorkerHealth';
import { isActiveRun, isFinishedRun, type RunHeader } from './useRun';

// Humanized "N ago" for a timestamp (or "never" when null).
function ago(iso: string | null): string {
  if (!iso) return 'never';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

interface Props {
  run: RunHeader;
  onCancel: () => void;
  onRetry: () => void;
  cancelling?: boolean;
  retrying?: boolean;
  actionError?: string | null;
}

// The run "cockpit": for any non-draft run it answers the two operator
// questions — is it healthy? and what's my next action? — with worker health,
// live progress, a cost meter, the failure reason, and a single state-appropriate
// action (Cancel while active, Retry once finished).
export function RunCockpit({ run, onCancel, onRetry, cancelling, retrying, actionError }: Props) {
  const wh = useWorkerHealth();
  const active = isActiveRun(run.state);
  const finished = isFinishedRun(run.state);

  const done = run.items_applied + run.items_flagged + run.items_failed;
  const total = run.task_count || 0;
  const pct = total ? Math.round((done / total) * 100) : 0;

  // Estimated time remaining: extrapolate from the run's own pace once at least
  // one item is done (elapsed ÷ done × remaining); before the first item, fall
  // back to the history/seed pre-run estimate. Rendered coarsely via bucketSeconds.
  const elapsedSec = run.started_at
    ? Math.max(0, (Date.now() - new Date(run.started_at).getTime()) / 1000)
    : 0;
  const preRun = useEstimatedRunSeconds(
    run.stage,
    run.llm_provider,
    run.llm_model,
    total,
    active && done === 0,
  );
  const etrSec = done > 0 ? (elapsedSec / done) * (total - done) : preRun?.seconds ?? null;

  const costActual = run.cost_actual_cents ?? 0;
  const cap = run.max_cost_cents;
  const capPct = cap ? Math.min(100, Math.round((costActual / cap) * 100)) : 0;

  const heartbeatStale =
    run.state === 'running' &&
    (run.last_heartbeat == null ||
      (Date.now() - new Date(run.last_heartbeat).getTime()) / 1000 > 60);

  const showHealth = active; // queued/claimed/running/cancelling
  const residue = run.items_pending + run.items_failed;

  return (
    <div className="runs-cockpit">
      {showHealth && (
        <div className={`runs-health ${wh.stale ? 'runs-health--warn' : 'runs-health--ok'}`}>
          {wh.stale
            ? `⚠ No worker seen ${wh.freshest ? ago(wh.freshest.last_seen) : 'ever'} — is the worker running?`
            : `✓ Worker active (seen ${wh.freshest ? ago(wh.freshest.last_seen) : ''})`}
          {run.state === 'running' && (
            <span className="runs-health__sub">
              {run.worker_id ? ` · on ${run.worker_id}` : ''} · heartbeat {ago(run.last_heartbeat)}
              {heartbeatStale ? ' ⚠ stalled' : ''}
            </span>
          )}
        </div>
      )}

      {(active || finished) && total > 0 && (
        <div className="runs-cockcard">
          <div className="runs-cockcard__label">Progress</div>
          <div className="runs-progress">
            <div className="runs-progress__bar" style={{ width: `${pct}%` }} />
          </div>
          <div className="runs-progress__meta">
            {done.toLocaleString()} / {total.toLocaleString()} items ({pct}%)
          </div>
          <div className="runs-chips">
            <span className="runs-badge runs-badge--applied">{run.items_applied.toLocaleString()} applied</span>
            <span className="runs-badge runs-badge--flagged">{run.items_flagged.toLocaleString()} flagged</span>
            <span className="runs-badge runs-badge--failed">{run.items_failed.toLocaleString()} failed</span>
            <span className="runs-badge runs-badge--pending">{run.items_pending.toLocaleString()} pending</span>
          </div>
          {active && etrSec != null && (
            <div className="runs-progress__meta">≈ {bucketSeconds(etrSec)} left</div>
          )}
        </div>
      )}

      {(active || finished) && (run.cost_actual_cents != null || cap != null) && (
        <div className="runs-cockcard">
          <div className="runs-cockcard__label">Cost</div>
          <div className="runs-meter">
            <div className="runs-meter__fill" style={{ width: `${capPct}%` }} />
          </div>
          <div className="runs-progress__meta">
            {formatCents(costActual)} spent{cap != null ? ` / ${formatCents(cap)} cap` : ''}
          </div>
        </div>
      )}

      {run.state === 'failed' && (
        <div className="runs-cockcard runs-cockcard--error">
          <div className="runs-cockcard__label">Why it failed</div>
          <div className="runs-errmsg">{run.error_detail ?? run.error_code ?? 'unknown error'}</div>
          {run.error_code === 'cost_cap_exceeded' && (
            <div className="runs-progress__meta">
              Stopped at the cost cap — raise it and retry to continue.
            </div>
          )}
        </div>
      )}

      {run.state === 'cancelled' && (
        <div className="runs-cockcard">
          <div className="runs-progress__meta">
            Cancelled — {done.toLocaleString()} of {total.toLocaleString()} processed,{' '}
            {run.items_pending.toLocaleString()} left pending.
          </div>
        </div>
      )}

      {actionError && <div className="tx-field__error">{actionError}</div>}

      <div className="runs-cockactions">
        {active && (
          <button
            type="button"
            className="runs-btn--danger"
            disabled={cancelling || run.state === 'cancelling'}
            onClick={onCancel}
          >
            {run.state === 'cancelling' || cancelling ? 'Cancelling…' : 'Cancel run'}
          </button>
        )}
        {finished && (
          <button type="button" className="runs-btn--primary" disabled={retrying} onClick={onRetry}>
            {retrying ? 'Retrying…' : residue > 0 ? `Retry residue (${residue.toLocaleString()}) →` : 'Re-run →'}
          </button>
        )}
      </div>
    </div>
  );
}
