import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../supabase';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { SplitView, DetailPane } from '../../ui/SplitView';
import { StatusPill } from '../../ui/StatusPill';
import { JsonView } from '../../ui/JsonView';
import { usePagedQuery, type PostgrestFilter } from '../../ui/hooks/usePagedQuery';
import { Pager } from '../../ui/Pager';

const PAGE_SIZE = 50;

interface AuditLogListRow {
  id: number;
  ts: string;
  table_name: string;
  pk: string;
  op: string;
  actor_kind: string;
  actor_id: string | null;
  source: string;
}

interface AuditLogDetailRow extends AuditLogListRow {
  before: unknown;
  after: unknown;
  changed_keys: string[] | null;
}

const ACTOR_KINDS = ['human', 'worker', 'system'];

const LIST_SELECT = 'id, ts, table_name, pk, op, actor_kind, actor_id, source';

const OP_LABELS: Record<string, string> = { I: 'insert', U: 'update', D: 'delete' };

const COLUMNS: DataTableColumn<AuditLogListRow>[] = [
  { key: 'ts', header: 'when' },
  { key: 'table_name', header: 'table' },
  { key: 'pk', header: 'pk' },
  { key: 'op', header: 'op', render: (r) => OP_LABELS[r.op] ?? r.op },
  { key: 'actor_kind', header: 'actor kind' },
  { key: 'actor_id', header: 'actor id', render: (r) => r.actor_id ?? '—' },
  { key: 'source', header: 'source' },
];

// The audit_log_public browser: actor legibility is the point (human vs
// worker vs system, and the source that triggered the write), plus a
// before/after diff on drill-down.
export function AuditLogBrowser() {
  const [actorKind, setActorKind] = useState('');
  const [tableName, setTableName] = useState('');
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [actorKind, tableName]);

  const filters: PostgrestFilter[] = [];
  if (actorKind) filters.push({ col: 'actor_kind', op: 'eq', value: actorKind });
  if (tableName) filters.push({ col: 'table_name', op: 'eq', value: tableName });

  const { rows, total } = usePagedQuery<AuditLogListRow>({
    table: 'audit_log_public',
    select: LIST_SELECT,
    filters,
    order: { col: 'id', asc: false },
    page,
    pageSize: PAGE_SIZE,
  });

  return (
    <div className="ops-audit-log">
      <div role="group" aria-label="audit log filters" style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
        <select aria-label="actor kind" value={actorKind} onChange={(e) => setActorKind(e.target.value)}>
          <option value="">All actors</option>
          {ACTOR_KINDS.map((k) => (
            <option key={k} value={k}>{k}</option>
          ))}
        </select>
        <input
          aria-label="table name"
          placeholder="table"
          value={tableName}
          onChange={(e) => setTableName(e.target.value)}
        />
      </div>
      <Pager page={page} pageSize={PAGE_SIZE} total={total} onPage={setPage} unit="entries" />
      <SplitView
        list={({ select }) => (
          <DataTable
            columns={COLUMNS}
            rows={rows}
            rowKey={(r) => r.id}
            onRowClick={(r) => select(String(r.id))}
          />
        )}
        detail={({ selectedId }) => <AuditLogDetail id={selectedId} />}
      />
    </div>
  );
}

function AuditLogDetail({ id }: { id: string | null }) {
  const query = useQuery({
    queryKey: ['auditLogDetail', id],
    queryFn: async () => {
      const { data, error } = await supabase
        .from('audit_log_public')
        .select('*')
        .eq('id', Number(id))
        .maybeSingle();
      if (error) throw error;
      return data as AuditLogDetailRow | null;
    },
    enabled: id != null,
  });

  if (id == null) return <DetailPane>Select an entry to see its detail.</DetailPane>;
  if (query.isPending) return <DetailPane>Loading…</DetailPane>;
  if (!query.data) return <DetailPane>Entry not found.</DetailPane>;

  const row = query.data;
  return (
    <DetailPane>
      <h3>{row.table_name} #{row.pk}</h3>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
        <StatusPill kind={row.actor_kind} />
        <span style={{ fontSize: 12, opacity: 0.7 }}>{row.source}</span>
      </div>
      <dl>
        <dt>op</dt>
        <dd>{OP_LABELS[row.op] ?? row.op}</dd>
        <dt>actor</dt>
        <dd>{row.actor_kind}{row.actor_id ? ` (${row.actor_id})` : ''}</dd>
        <dt>when</dt>
        <dd>{row.ts}</dd>
      </dl>
      {row.changed_keys && row.changed_keys.length > 0 && (
        <p style={{ fontSize: 12, opacity: 0.7 }}>
          changed: {row.changed_keys.join(', ')}
        </p>
      )}
      <JsonView value={row.before} name="before" />
      <JsonView value={row.after} name="after" />
    </DetailPane>
  );
}
