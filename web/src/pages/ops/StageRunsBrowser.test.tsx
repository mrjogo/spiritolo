import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const fromMock = vi.fn();
vi.mock('../../supabase', () => ({ supabase: { from: (table: string) => fromMock(table) } }));

import { StageRunsBrowser } from './StageRunsBrowser';

interface RunRow {
  id: number;
  entity_type: string;
  entity_id: number;
  stage: string;
  code_version: string;
  outcome: string;
  method: string;
  cost_cents: number | null;
  started_at: string;
  finished_at: string | null;
}

// usePagedQuery always calls .select(sel, {count:'exact'}); the detail fetch
// always calls .select('*') with no options — dispatch on that shape rather
// than on call order, since the list re-queries on every filter change.
function mockSupabase(rows: RunRow[], detailRow: unknown = null) {
  const listEqCalls: [string, unknown][] = [];
  const range = vi.fn().mockResolvedValue({ data: rows, count: rows.length, error: null });
  const listChain: Record<string, unknown> = {};
  listChain.eq = vi.fn((col: string, value: unknown) => { listEqCalls.push([col, value]); return listChain; });
  listChain.order = vi.fn(() => ({ range }));

  const maybeSingle = vi.fn().mockResolvedValue({ data: detailRow, error: null });
  const detailEq = vi.fn(() => ({ maybeSingle }));

  fromMock.mockImplementation((table: string) => {
    if (table !== 'job_items') throw new Error(`unexpected table ${table}`);
    return {
      select: (_sel: string, opts?: { count?: string }) =>
        (opts && opts.count ? listChain : { eq: detailEq }),
    };
  });

  return { listEqCalls, detailEq, maybeSingle };
}

function renderBrowser(client: QueryClient) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  }
  return render(<StageRunsBrowser />, { wrapper: Wrapper });
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

beforeEach(() => {
  fromMock.mockReset();
});

describe('<StageRunsBrowser>', () => {
  it('lists job_items rows with outcome as a StatusPill', async () => {
    mockSupabase([
      { id: 1, entity_type: 'recipe', entity_id: 10, stage: 'parse-ingredients', code_version: 'v10', outcome: 'resolved', method: 'deterministic', cost_cents: 0, started_at: '2026-07-01T00:00:00Z', finished_at: null },
    ]);
    renderBrowser(makeClient());
    // Scoped to the table: 'parse-ingredients'/'resolved' also appear as filter <option>
    // values, so an unscoped query would be ambiguous once data loads.
    const table = await screen.findByRole('table');
    expect(await within(table).findByText('parse-ingredients')).toBeInTheDocument();
    expect(within(table).getByText('resolved')).toBeInTheDocument();
  });

  it('selecting a row fetches and renders its full detail including payload', async () => {
    const { detailEq } = mockSupabase(
      [{ id: 1, entity_type: 'recipe', entity_id: 10, stage: 'parse-ingredients', code_version: 'v10', outcome: 'resolved', method: 'deterministic', cost_cents: 0, started_at: '2026-07-01T00:00:00Z', finished_at: null }],
      { id: 1, entity_type: 'recipe', entity_id: 10, stage: 'parse-ingredients', code_version: 'v10', outcome: 'resolved', method: 'deterministic', cost_cents: 0, started_at: '2026-07-01T00:00:00Z', finished_at: null, payload: { structured: 3 } },
    );
    renderBrowser(makeClient());
    const row = await within(await screen.findByRole('table')).findByRole('button');
    await userEvent.click(row);
    await waitFor(() => expect(detailEq).toHaveBeenCalledWith('id', 1));
    expect(await screen.findByText(/structured/)).toBeInTheDocument();
  });

  it('applies the stage/outcome/version filters to the underlying query', async () => {
    const { listEqCalls } = mockSupabase([]);
    renderBrowser(makeClient());

    await userEvent.selectOptions(screen.getByLabelText('stage'), 'map-ingredient');
    await userEvent.selectOptions(screen.getByLabelText('outcome'), 'failed');
    await userEvent.type(screen.getByLabelText('version'), 'v2');

    await waitFor(() => {
      expect(listEqCalls).toContainEqual(['stage', 'map-ingredient']);
      expect(listEqCalls).toContainEqual(['outcome', 'failed']);
      expect(listEqCalls).toContainEqual(['code_version', 'v2']);
    });
  });
});
