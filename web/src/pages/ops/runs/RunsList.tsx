import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { usePagedQuery } from '../../../ui/hooks/usePagedQuery';
import { Pager } from '../../../ui/Pager';
import { PIPELINE_STAGES } from '../../../ui/pipelineStages';
import { useCreateRun, type RunState } from '../../../ui/runs/useRun';
import './runs.css';

const PAGE_SIZE = 25;

interface RunListRow {
  id: number;
  stage: string;
  state: RunState;
  task_count: number;
  created_at: string | null;
  created_by: string | null;
}

const LIST_SELECT = 'id, stage, state, task_count, created_at, created_by';

// The runs index: every run (a `jobs` row surfaced through the `runs` view),
// newest first, plus a "New run" affordance that create_run()s a draft for a
// chosen stage and drops you straight into its detail page to load tasks.
export function RunsList() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [newStage, setNewStage] = useState<string>(PIPELINE_STAGES[5]); // map-ingredient

  const { rows, total, status } = usePagedQuery<RunListRow>({
    table: 'runs',
    select: LIST_SELECT,
    order: { col: 'id', asc: false },
    page,
    pageSize: PAGE_SIZE,
  });

  const createRun = useCreateRun();

  async function handleCreate() {
    const jobId = await createRun.mutateAsync({ stage: newStage });
    navigate(`/ops/runs/${jobId}`);
  }

  const isEmpty = status === 'loaded' && rows.length === 0;

  return (
    <div className="ops-runs-list">
      <div className="runs-head">
        <h1 className="runs-title">Runs</h1>
        {!creating ? (
          <button type="button" className="runs-btn--primary" onClick={() => setCreating(true)}>
            ＋ New run
          </button>
        ) : (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <select aria-label="new run stage" value={newStage} onChange={(e) => setNewStage(e.target.value)}>
              {PIPELINE_STAGES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <button
              type="button"
              className="runs-btn--primary"
              disabled={createRun.isPending}
              onClick={handleCreate}
            >
              Create draft →
            </button>
            <button type="button" onClick={() => setCreating(false)} disabled={createRun.isPending}>
              Cancel
            </button>
          </div>
        )}
      </div>

      {createRun.isError && (
        <div className="tx-field__error" style={{ marginBottom: 12 }}>
          {createRun.error.message}
        </div>
      )}

      {isEmpty ? (
        <div className="runs-empty">
          <h3>No runs yet</h3>
          <p>
            A run loads a set of a stage's entities into the queue, then starts the worker over
            just that set. Create your first draft to pick a stage and add tasks.
          </p>
          {!creating && (
            <button type="button" className="runs-btn--primary" onClick={() => setCreating(true)}>
              ＋ New run
            </button>
          )}
        </div>
      ) : (
        <>
          <div className="runs-panel">
            <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th scope="col">Run</th>
                  <th scope="col">Stage</th>
                  <th scope="col">State</th>
                  <th scope="col">Tasks</th>
                  <th scope="col">Created</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td data-label="Run">
                      <Link className="ops-xlink" to={`/ops/runs/${r.id}`}>Run #{r.id}</Link>
                    </td>
                    <td data-label="Stage"><span className="runs-stage-pill">{r.stage}</span></td>
                    <td data-label="State">
                      <span className={`runs-state runs-state--${r.state}`}>{r.state}</span>
                    </td>
                    <td data-label="Tasks">{r.task_count?.toLocaleString() ?? '0'}</td>
                    <td data-label="Created">{r.created_at ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager page={page} pageSize={PAGE_SIZE} total={total} onPage={setPage} unit="runs" />
        </>
      )}
    </div>
  );
}
