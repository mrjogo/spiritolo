import type { RunState } from './useRun';

// The in-run status filter chips. `key: null` is "All"; the rest map onto the
// p_filter status vocabulary the run_items facets are keyed by. Kept in a
// non-component module so TasksTable.tsx can stay fast-refresh-clean.
export interface StatusChip {
  key: string | null;
  label: string;
}

export const RUN_STATUS_CHIPS: StatusChip[] = [
  { key: null, label: 'All' },
  { key: 'flagged', label: 'Flagged' },
  { key: 'never_run', label: 'Never run' },
  { key: 'failed', label: 'Failed' },
];

// The batch bar changes meaning with the run's lifecycle:
//   - draft            → destructive "Remove from run" (curating the set)
//   - anything else    → inspect-only (you can look, not mutate mid-flight)
export type BatchMode = 'remove' | 'inspect';

export function batchMode(runState: RunState): BatchMode {
  if (runState === 'draft') return 'remove';
  return 'inspect';
}
