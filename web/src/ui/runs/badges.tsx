import type { WhyAdded, TaskStatus } from './useRunItems';

// Maps the "why added" reason to the dot-badge look + human label used in the
// Run-detail and Add-tasks tables (see .runs-badge--* in runs.css).
const WHY_LABEL: Record<WhyAdded, string> = {
  flagged: 'flagged',
  never_run: 'never run',
  retry_failed: 'retry failed',
  applied: 'applied',
  pending_apply: 'pending apply',
};

const WHY_VARIANT: Record<WhyAdded, string> = {
  flagged: 'flagged',
  never_run: 'never',
  retry_failed: 'failed',
  applied: 'applied',
  pending_apply: 'pending',
};

export function WhyAddedBadge({ why, detail }: { why: WhyAdded; detail?: string }) {
  const variant = WHY_VARIANT[why] ?? 'never';
  const label = WHY_LABEL[why] ?? why;
  return <span className={`runs-badge runs-badge--${variant}`}>{detail ?? label}</span>;
}

// A generic status badge for the eligible-pool "map status" column, which is a
// free-ish string ("flagged", "failed", "never_run", "applied", ...).
const STATUS_VARIANT: Record<string, string> = {
  flagged: 'flagged',
  failed: 'failed',
  never_run: 'never',
  applied: 'applied',
  pending_apply: 'pending',
  pending: 'pending',
  running: 'pending',
};

export function StatusBadge({ status, detail }: { status: string; detail?: string }) {
  const variant = STATUS_VARIANT[status] ?? 'never';
  const label = status.replace(/_/g, ' ');
  return <span className={`runs-badge runs-badge--${variant}`}>{detail ?? label}</span>;
}

// The in-run task state chip (queued / running / applied / …). Neutral grey
// pill; matches the mockup's small ".qchip".
const TASK_STATE_LABEL: Record<TaskStatus, string> = {
  pending: 'queued',
  running: 'running',
  applied: 'applied',
  pending_apply: 'pending apply',
  flagged: 'flagged',
  failed: 'failed',
};

export function TaskStateChip({ state }: { state: TaskStatus }) {
  return <span className="runs-qchip">{TASK_STATE_LABEL[state] ?? state}</span>;
}
