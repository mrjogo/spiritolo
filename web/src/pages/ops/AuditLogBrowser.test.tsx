import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const fromMock = vi.fn();
vi.mock('../../supabase', () => ({ supabase: { from: (table: string) => fromMock(table) } }));

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

function mockSupabase(rows: LogRow[], detailRow: unknown = null) {
  const listEqCalls: [string, unknown][] = [];
  const range = vi.fn().mockResolvedValue({ data: rows, count: rows.length, error: null });
  const listChain: Record<string, unknown> = {};
  listChain.eq = vi.fn((col: string, value: unknown) => { listEqCalls.push([col, value]); return listChain; });
  listChain.order = vi.fn(() => ({ range }));

  const maybeSingle = vi.fn().mockResolvedValue({ data: detailRow, error: null });
  const detailEq = vi.fn(() => ({ maybeSingle }));

  fromMock.mockImplementation((table: string) => {
    if (table !== 'audit_log_public') throw new Error(`unexpected table ${table}`);
    return {
      select: (_sel: string, opts?: { count?: string }) =>
        (opts && opts.count ? listChain : { eq: detailEq }),
    };
  });

  return { listEqCalls, detailEq };
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
  fromMock.mockReset();
});

describe('<AuditLogBrowser>', () => {
  it('lists audit_log_public rows with actor legibility (kind + id)', async () => {
    mockSupabase([
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
    const { listEqCalls } = mockSupabase([]);
    renderBrowser(makeClient());
    await userEvent.selectOptions(screen.getByLabelText('actor kind'), 'system');
    await waitFor(() => expect(listEqCalls).toContainEqual(['actor_kind', 'system']));
  });

  it('selecting a row shows the before/after diff and changed_keys', async () => {
    const { detailEq } = mockSupabase(
      [{ id: 1, ts: '2026-07-01T00:00:00Z', table_name: 'recipes', pk: '10', op: 'U', actor_kind: 'human', actor_id: 'abc-123', source: 'manual-ui-edit' }],
      {
        id: 1, ts: '2026-07-01T00:00:00Z', table_name: 'recipes', pk: '10', op: 'U',
        actor_kind: 'human', actor_id: 'abc-123', source: 'manual-ui-edit',
        before: { title: 'Old' }, after: { title: 'New' }, changed_keys: ['title'],
      },
    );
    renderBrowser(makeClient());
    const row = await screen.findByRole('button');
    await userEvent.click(row);
    await waitFor(() => expect(detailEq).toHaveBeenCalledWith('id', 1));
    expect(await screen.findByText('"New"')).toBeInTheDocument();
    expect(screen.getByText('"Old"')).toBeInTheDocument();
  });
});
