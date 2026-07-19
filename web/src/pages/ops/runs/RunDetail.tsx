import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { formatCents } from '../../../ui/formatCents';
import { LlmTierSelect } from '../../../ui/runs/LlmTierSelect';
import { StartConfirmModal } from '../../../ui/runs/StartConfirmModal';
import { TasksTable } from '../../../ui/runs/TasksTable';
import { useRun, useSetRunLlm, useStartRun } from '../../../ui/runs/useRun';
import {
  useRunItems,
  useRemoveRunItems,
  useApplyRunItems,
  type Sort,
} from '../../../ui/runs/useRunItems';
import { buildPFilter, type RunFilterState } from '../../../ui/runs/filter';
import type { LlmTier } from '../../../ui/runs/llmTiers';
import { useEstimatedRunCents } from '../../../ui/runs/useEstimate';
import './runs.css';

const PAGE_SIZE = 50;
const DEFAULT_SORT: Sort = { col: 'title', asc: true };

// The run detail: header + state badge, the LLM-tier picker + cost estimate,
// the Start-run affordance (metered → confirm modal), and the task list with
// status chips / search / pagination and a lifecycle-aware batch bar.
export function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const jobId = id ? Number(id) : null;

  const { run, tier, status: runStatus } = useRun(jobId);

  // Local overrides so the picker feels instant; persisted via set_run_llm.
  const [tierOverride, setTierOverride] = useState<LlmTier | null>(null);
  const activeTier = tierOverride ?? tier;

  const [activeStatus, setActiveStatus] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [modalOpen, setModalOpen] = useState(false);

  const filterState: RunFilterState = {
    status: activeStatus ? [activeStatus] : [],
    source: [],
    search: search || undefined,
  };
  const pFilter = buildPFilter(filterState);

  const { rows, total, facets } = useRunItems(jobId, pFilter, DEFAULT_SORT, page, PAGE_SIZE);

  const setLlm = useSetRunLlm(jobId ?? 0);
  const startRun = useStartRun(jobId ?? 0);
  const removeItems = useRemoveRunItems(jobId ?? 0);
  const applyItems = useApplyRunItems(jobId ?? 0);

  // Live draft estimate from the server (single source of truth); must be called
  // before the early returns to respect the rules of hooks.
  const draftEstimate = useEstimatedRunCents(
    activeTier?.provider,
    activeTier?.model,
    run?.task_count,
    run?.state === 'draft',
  );

  if (runStatus === 'loading') return <div className="ops-run-detail">Loading…</div>;
  if (!run || jobId == null) {
    return (
      <div className="ops-run-detail">
        <div className="runs-crumb"><Link to="/ops/runs">Runs</Link> / <b>not found</b></div>
        <p>Run not found.</p>
      </div>
    );
  }

  const isDraft = run.state === 'draft';
  const estimateCents = run.cost_estimate_cents ?? draftEstimate;

  function handleTierChange(next: LlmTier) {
    setTierOverride(next);
    setLlm.mutate({ job_id: run!.id, provider: next.provider, model: next.model });
  }

  function handleStart(maxCostCents: number) {
    startRun.mutate(
      { job_id: run!.id, max_cost_cents: maxCostCents },
      { onSuccess: () => setModalOpen(false) },
    );
  }

  return (
    <div className="ops-run-detail">
      <div className="runs-crumb">
        <Link to="/ops/runs">Runs</Link> / <b>Run #{run.id}</b>
      </div>

      <div className="runs-head">
        <div>
          <h1 className="runs-title">
            Run #{run.id}
            <span className="runs-stage-pill">{run.stage}</span>
            <span className={`runs-state runs-state--${run.state}`}>{run.state}</span>
          </h1>
          <div className="runs-meta">
            created by {run.created_by ?? 'unknown'}
            {run.state === 'draft' ? ' · not started' : ` · ${run.state}`}
          </div>
        </div>
        <Link to={`/ops/runs/${run.id}/add`} className="ops-xlink">
          <button type="button" className="runs-btn--primary">＋ Add tasks</button>
        </Link>
      </div>

      <div className="runs-ctl">
        <div className="runs-ctlcard">
          <span className="runs-ctlcard__label">LLM tier for this run</span>
          <LlmTierSelect value={activeTier} onChange={handleTierChange} disabled={!isDraft} />
        </div>
        <div className="runs-ctlcard">
          <span className="runs-ctlcard__label">Estimated cost</span>
          <div className="runs-esti">
            <span className="runs-esti__amt">≈ {formatCents(estimateCents)}</span>
            {activeTier.metered && <span className="runs-tag">metered</span>}
          </div>
          <div className="runs-meta">
            {run.task_count.toLocaleString()} tasks · deterministic tier first, LLM on residue
          </div>
        </div>
        <div className="runs-ctlcard runs-startcard">
          <button
            type="button"
            className="runs-btn--primary"
            disabled={!isDraft || run.task_count === 0}
            onClick={() => setModalOpen(true)}
          >
            Start run →
          </button>
          <div className="runs-startcard__fine">
            {activeTier.metered ? 'metered — needs approval to start' : 'free — starts immediately'}
          </div>
        </div>
      </div>

      <TasksTable
        runState={run.state}
        applyMode={run.apply_mode}
        items={rows}
        total={total}
        statusFacets={facets.status ?? {}}
        activeStatus={activeStatus}
        onStatus={(s) => { setActiveStatus(s); setPage(1); }}
        search={search}
        onSearch={(v) => { setSearch(v); setPage(1); }}
        page={page}
        pageSize={PAGE_SIZE}
        onPage={setPage}
        selectedIds={selectedIds}
        onSelectionChange={(ids) => setSelectedIds(new Set(ids))}
        onRemove={(ids) => removeItems.mutate({ job_id: run.id, item_ids: ids }, {
          onSuccess: () => setSelectedIds(new Set()),
        })}
        onApply={(ids) => applyItems.mutate({ job_id: run.id, item_ids: ids }, {
          onSuccess: () => setSelectedIds(new Set()),
        })}
      />

      {modalOpen && (
        <StartConfirmModal
          run={run}
          tier={activeTier}
          submitting={startRun.isPending}
          error={startRun.isError ? startRun.error.message : null}
          onCancel={() => setModalOpen(false)}
          onStart={handleStart}
        />
      )}
    </div>
  );
}
