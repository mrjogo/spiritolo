import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const queryTableMock = vi.fn();
const queryOneMock = vi.fn();
const queryAllMock = vi.fn();
vi.mock('../../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api')>()),
  queryTable: (...args: unknown[]) => queryTableMock(...args),
  queryOne: (...args: unknown[]) => queryOneMock(...args),
  queryAll: (...args: unknown[]) => queryAllMock(...args),
}));

import { AuditLogBrowser } from './AuditLogBrowser';

interface LogRow {
  id: number;
  ts: string;
  table_name: string;
  pk: string;
  op: string;
  actor_kind: string;
  actor_id: string | null;
  source: string;
}

function mockApi(rows: LogRow[], detailRow: unknown = null) {
  const specs: { table: string; filters?: { col: string; value: unknown }[] }[] = [];
  queryTableMock.mockImplementation(async (spec: { table: string; filters?: { col: string; value: unknown }[] }) => {
    if (spec.table !== 'audit_log_public') throw new Error(`unexpected table ${spec.table}`);
    specs.push(spec);
    return { rows, total: rows.length };
  });
  queryOneMock.mockImplementation(async (table: string) => {
    if (table !== 'audit_log_public') throw new Error(`unexpected table ${table}`);
    return detailRow;
  });
  const listEqCalls = (): [string, unknown][] =>
    specs.flatMap((s) => (s.filters ?? []).map((f) => [f.col, f.value] as [string, unknown]));
  return { listEqCalls, detailEq: queryOneMock };
}

function renderBrowser(client: QueryClient) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  }
  return render(<AuditLogBrowser />, { wrapper: Wrapper });
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

beforeEach(() => {
  queryTableMock.mockReset();
  queryOneMock.mockReset();
  queryAllMock.mockReset();
});

describe('<AuditLogBrowser>', () => {
  it('lists audit_log_public rows with actor legibility (kind + id)', async () => {
    mockApi([
      { id: 1, ts: '2026-07-01T00:00:00Z', table_name: 'recipes', pk: '10', op: 'U', actor_kind: 'human', actor_id: 'abc-123', source: 'manual-ui-edit' },
      { id: 2, ts: '2026-07-01T00:00:01Z', table_name: 'recipes', pk: '11', op: 'I', actor_kind: 'worker', actor_id: '42', source: 'job:parse' },
    ]);
    renderBrowser(makeClient());
    // Scoped to the table: 'human'/'worker' also appear as filter <option>
    // values, so an unscoped query would be ambiguous once data loads.
    const table = await screen.findByRole('table');
    expect(await within(table).findByText('human')).toBeInTheDocument();
    expect(within(table).getByText('worker')).toBeInTheDocument();
    expect(within(table).getByText('job:parse')).toBeInTheDocument();
  });

  it('filters by actor_kind', async () => {
    const { listEqCalls } = mockApi([]);
    renderBrowser(makeClient());
    await userEvent.selectOptions(screen.getByLabelText('actor kind'), 'system');
    await waitFor(() => expect(listEqCalls()).toContainEqual(['actor_kind', 'system']));
  });

  it('selecting a row shows the before/after diff and changed_keys', async () => {
    const { detailEq } = mockApi(
      [{ id: 1, ts: '2026-07-01T00:00:00Z', table_name: 'recipes', pk: '10', op: 'U', actor_kind: 'human', actor_id: 'abc-123', source: 'manual-ui-edit' }],
      {
        id: 1, ts: '2026-07-01T00:00:00Z', table_name: 'recipes', pk: '10', op: 'U',
        actor_kind: 'human', actor_id: 'abc-123', source: 'manual-ui-edit',
        before: { title: 'Old' }, after: { title: 'New' }, changed_keys: ['title'],
      },
    );
    renderBrowser(makeClient());
    const row = await within(await screen.findByRole('table')).findByRole('button');
    await userEvent.click(row);
    await waitFor(() => expect(detailEq).toHaveBeenCalledWith('audit_log_public', [{ col: 'id', op: 'eq', value: 1 }]));
    expect(await screen.findByText('"New"')).toBeInTheDocument();
    expect(screen.getByText('"Old"')).toBeInTheDocument();
  });

  it('explains that insert rows store no payload', async () => {
    const row = {
      id: 7, ts: '2026-08-04T00:00:00Z', table_name: 'recipes', pk: '99',
      op: 'I', actor_kind: 'worker', actor_id: '42', source: 'job:extract-recipe',
    };
    mockApi([row], { ...row, before: null, after: null, changed_keys: null });
    renderBrowser(makeClient());

    await userEvent.click(await within(await screen.findByRole('table')).findByRole('button'));

    expect(await screen.findByText(/payload not stored/i)).toBeInTheDocument();
    // The bare `before:`/`after:` leaves would imply a stored (null) image.
    expect(screen.queryByText('before:')).not.toBeInTheDocument();
    expect(screen.queryByText('after:')).not.toBeInTheDocument();
  });

  it('labels update images as the changed-key subset', async () => {
    const row = {
      id: 8, ts: '2026-08-04T00:00:00Z', table_name: 'recipes', pk: '99',
      op: 'U', actor_kind: 'worker', actor_id: '42', source: 'job:extract-recipe',
    };
    mockApi([row], {
      ...row,
      before: { title: 'Old' },
      after: { title: 'New' },
      changed_keys: ['title'],
    });
    renderBrowser(makeClient());

    await userEvent.click(await within(await screen.findByRole('table')).findByRole('button'));

    expect(await screen.findByText('before (changed keys only):')).toBeInTheDocument();
    expect(screen.getByText('after (changed keys only):')).toBeInTheDocument();
  });

  it('leaves the delete pre-image labelled as a full row', async () => {
    const row = {
      id: 9, ts: '2026-08-04T00:00:00Z', table_name: 'recipes', pk: '99',
      op: 'D', actor_kind: 'system', actor_id: null, source: 'hand-sql',
    };
    mockApi([row], {
      ...row,
      before: { title: 'Gone' },
      after: null,
      changed_keys: null,
    });
    renderBrowser(makeClient());

    await userEvent.click(await within(await screen.findByRole('table')).findByRole('button'));

    expect(await screen.findByText('before:')).toBeInTheDocument();
    expect(screen.queryByText('before (changed keys only):')).not.toBeInTheDocument();
  });
});
