import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../supabase';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { SplitView, DetailPane } from '../../ui/SplitView';
import { StatusPill } from '../../ui/StatusPill';
import { CostBadge } from '../../ui/CostBadge';
import { JsonView } from '../../ui/JsonView';
import { usePagedQuery, type PostgrestFilter } from '../../ui/hooks/usePagedQuery';
import { PIPELINE_STAGES } from '../../ui/pipelineStages';

interface StageRunListRow {
  id: number;
  entity_type: string;
  entity_id: number;
  stage: string;
  version: string;
  outcome: string;
  method: string;
  cost_cents: number | null;
  started_at: string;
}

interface StageRunDetailRow extends StageRunListRow {
  confidence: number | null;
  model_id: string | null;
  error_code: string | null;
  batch_id: number | null;
  job_id: number | null;
  finished_at: string | null;
  payload: unknown;
}

const OUTCOMES = ['resolved', 'abstain', 'pending', 'failed', 'proposes_new'];

const LIST_SELECT =
  'id, entity_type, entity_id, stage, version, outcome, method, cost_cents, started_at';

const COLUMNS: DataTableColumn<StageRunListRow>[] = [
  { key: 'id', header: 'id' },
  { key: 'stage', header: 'stage' },
  { key: 'entity_type', header: 'entity' },
  { key: 'entity_id', header: 'entity id' },
  { key: 'version', header: 'version' },
  { key: 'outcome', header: 'outcome', render: (r) => <StatusPill kind={r.outcome} /> },
  {
    key: 'cost_cents',
    header: 'cost',
    render: (r) => <CostBadge cents={r.cost_cents} metered={(r.cost_cents ?? 0) > 0} />,
  },
  { key: 'started_at', header: 'started' },
];

// The stage_runs run-ledger: filter by stage/outcome/version, drill from the
// list into the full row (including payload) on selection.
export function StageRunsBrowser() {
  const [stage, setStage] = useState('');
  const [outcome, setOutcome] = useState('');
  const [version, setVersion] = useState('');

  const filters: PostgrestFilter[] = [];
  if (stage) filters.push({ col: 'stage', op: 'eq', value: stage });
  if (outcome) filters.push({ col: 'outcome', op: 'eq', value: outcome });
  if (version) filters.push({ col: 'version', op: 'eq', value: version });

  const { rows, total } = usePagedQuery<StageRunListRow>({
    table: 'stage_runs',
    select: LIST_SELECT,
    filters,
    order: { col: 'id', asc: false },
    page: 1,
    pageSize: 50,
  });

  return (
    <div className="ops-stage-runs">
      <div role="group" aria-label="stage run filters" style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
        <select aria-label="stage" value={stage} onChange={(e) => setStage(e.target.value)}>
          <option value="">All stages</option>
          {PIPELINE_STAGES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select aria-label="outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
          <option value="">All outcomes</option>
          {OUTCOMES.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
        <input
          aria-label="version"
          placeholder="version"
          value={version}
          onChange={(e) => setVersion(e.target.value)}
        />
      </div>
      <p style={{ fontSize: 12, opacity: 0.7 }}>{total} runs</p>
      <SplitView
        list={({ select }) => (
          <DataTable
            columns={COLUMNS}
            rows={rows}
            rowKey={(r) => r.id}
            onRowClick={(r) => select(String(r.id))}
          />
        )}
        detail={({ selectedId }) => <StageRunDetail id={selectedId} />}
      />
    </div>
  );
}

function StageRunDetail({ id }: { id: string | null }) {
  const query = useQuery({
    queryKey: ['stageRunDetail', id],
    queryFn: async () => {
      const { data, error } = await supabase
        .from('stage_runs')
        .select('*')
        .eq('id', Number(id))
        .maybeSingle();
      if (error) throw error;
      return data as StageRunDetailRow | null;
    },
    enabled: id != null,
  });

  if (id == null) return <DetailPane>Select a run to see its detail.</DetailPane>;
  if (query.isPending) return <DetailPane>Loading…</DetailPane>;
  if (!query.data) return <DetailPane>Run not found.</DetailPane>;

  const row = query.data;
  return (
    <DetailPane>
      <h3>Run #{row.id}</h3>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
        <StatusPill kind={row.outcome} />
        <CostBadge cents={row.cost_cents} metered={(row.cost_cents ?? 0) > 0} variant="actual" />
      </div>
      <dl>
        <dt>entity</dt>
        <dd>{row.entity_type} #{row.entity_id}</dd>
        <dt>stage / version</dt>
        <dd>{row.stage} @ {row.version}</dd>
        <dt>method</dt>
        <dd>{row.method}{row.model_id ? ` (${row.model_id})` : ''}</dd>
        {row.error_code && (
          <>
            <dt>error</dt>
            <dd>{row.error_code}</dd>
          </>
        )}
        <dt>started / finished</dt>
        <dd>{row.started_at} → {row.finished_at ?? '—'}</dd>
      </dl>
      <JsonView value={row.payload} name="payload" />
    </DetailPane>
  );
}
