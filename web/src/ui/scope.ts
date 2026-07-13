import type { PostgrestFilter } from './hooks/usePagedQuery';

// The four shapes of "what to run this stage over." One TriggerBar instance
// builds exactly one of these from its props and hands it straight through
// to enqueue_job's payload — never re-derived once built, so what the UI
// shows and what the job acts on can't drift apart (see FilterBar, which
// emits the 'filter' variant that a TriggerBar forwards unchanged).
export type ScopeDescriptor =
  | { kind: 'item'; stage: string; entity_id: string }
  | { kind: 'multiselect'; stage: string; entity_ids: string[] }
  | { kind: 'filter'; stage?: string; site?: string; limit?: number; where?: PostgrestFilter[] }
  | { kind: 'whole_queue'; stage: string };

export type FilterScopeDescriptor = Extract<ScopeDescriptor, { kind: 'filter' }>;
