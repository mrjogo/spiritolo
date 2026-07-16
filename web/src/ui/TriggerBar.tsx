import { useState } from 'react';
import { useStageConfig, isMetered } from './stageConfig';
import { useRpc } from './hooks/useRpc';
import { useRealtimeJobs } from './hooks/useRealtimeJobs';
import { Toast } from './Toast';
import { CostConfirmModal } from './CostConfirmModal';
import type { ScopeDescriptor, FilterScopeDescriptor } from './scope';

// A type alias (not an interface) — see CostConfirmModal.tsx for why this
// matters for useRpc's generic constraint.
type EnqueueArgs = {
  p_stage: string;
  p_kind: string;
  p_payload: { scope: ScopeDescriptor };
  p_version: string | null;
  p_requires_approval: boolean;
  p_cost_estimate_cents: number | null;
  p_max_cost_cents: number | null;
};

interface Props {
  stage: string;
  version?: string;
  /** 'item' scope: acting on exactly one entity. */
  entityId?: string;
  /** 'multiselect' scope: acting on the current DataTable selection. */
  selectedIds?: (string | number)[];
  /** 'filter' scope: the object FilterBar emitted for the current view —
   *  forwarded to enqueue unchanged so what-you-see == what-you-act-on. */
  filterScope?: FilterScopeDescriptor;
  /** Known item count for the cost-confirm estimate (e.g. selection size or
   *  a filtered total). Omitted when unknowable (whole_queue with no
   *  queue-depth surface yet) rather than guessed. */
  itemCount?: number;
}

// Builds the ScopeDescriptor for this trigger from whichever of
// entityId/selectedIds/filterScope was supplied, falling back to
// whole_queue. Exactly one of the four shapes results — never a mix.
function buildScope(props: Pick<Props, 'stage' | 'entityId' | 'selectedIds' | 'filterScope'>): ScopeDescriptor {
  if (props.entityId !== undefined) {
    return { kind: 'item', stage: props.stage, entity_id: props.entityId };
  }
  if (props.selectedIds !== undefined) {
    return { kind: 'multiselect', stage: props.stage, entity_ids: props.selectedIds.map(String) };
  }
  if (props.filterScope !== undefined) {
    return props.filterScope;
  }
  return { kind: 'whole_queue', stage: props.stage };
}

function scopeRunLabel(scope: ScopeDescriptor): string {
  switch (scope.kind) {
    case 'item': return 'Run item';
    case 'multiselect': return `Run ${scope.entity_ids.length} selected`;
    case 'filter': return 'Run filtered';
    case 'whole_queue': return 'Run queue';
  }
}

function defaultItemCount(scope: ScopeDescriptor, itemCount: number | undefined): number | undefined {
  if (itemCount !== undefined) return itemCount;
  if (scope.kind === 'item') return 1;
  if (scope.kind === 'multiselect') return scope.entity_ids.length;
  return undefined; // filter/whole_queue: unknown unless the caller tells us
}

export function TriggerBar({ stage, version, entityId, selectedIds, filterScope, itemCount }: Props) {
  const { rows } = useStageConfig();
  const metered = isMetered(rows, stage);
  const scope = buildScope({ stage, entityId, selectedIds, filterScope });

  const enqueue = useRpc<EnqueueArgs, number>('enqueue_job', { invalidate: [['jobs']] });
  const [modalOpen, setModalOpen] = useState(false);
  const [trackedJobId, setTrackedJobId] = useState<number | null>(null);

  function handleRun() {
    if (metered) {
      setModalOpen(true);
      return;
    }
    enqueue.mutate(
      {
        p_stage: stage,
        p_kind: 'run',
        p_payload: { scope },
        p_version: version ?? null,
        p_requires_approval: false,
        p_cost_estimate_cents: null,
        p_max_cost_cents: null,
      },
      { onSuccess: (jobId) => setTrackedJobId(jobId) },
    );
  }

  return (
    <div className="trigger-bar">
      <button type="button" onClick={handleRun}>
        {scopeRunLabel(scope)}
      </button>

      {modalOpen && (
        <CostConfirmModal
          stage={stage}
          scope={scope}
          version={version}
          itemCount={defaultItemCount(scope, itemCount)}
          onCancel={() => setModalOpen(false)}
          onConfirmed={(jobId) => {
            setModalOpen(false);
            setTrackedJobId(jobId);
          }}
        />
      )}

      {trackedJobId != null && (
        <JobProgressToast
          stage={stage}
          jobId={trackedJobId}
          onDone={() => setTrackedJobId(null)}
        />
      )}
    </div>
  );
}

// Tracks one enqueued job live via the existing useRealtimeJobs({stage})
// subscription (no bespoke polling) and shows a persistent Toast until the
// job reaches a terminal state.
function JobProgressToast({ stage, jobId, onDone }: { stage: string; jobId: number; onDone: () => void }) {
  const { jobs } = useRealtimeJobs({ stage });
  const job = jobs.find((j) => String(j.id) === String(jobId));
  const state = (job?.state as string | undefined) ?? 'queued';
  const done = state === 'succeeded' || state === 'failed';
  return (
    <Toast
      message={`Job #${jobId}: ${state}`}
      kind={done ? (state === 'failed' ? 'error' : 'info') : 'progress'}
      persist={!done}
      onDismiss={onDone}
    />
  );
}
