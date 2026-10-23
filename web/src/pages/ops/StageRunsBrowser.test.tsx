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

// The list goes through queryTable (paged), the detail through queryOne.
function mockApi(rows: RunRow[], detailRow: unknown = null) {
  const specs: { table: string; filters?: { col: string; value: unknown }[] }[] = [];
  queryTableMock.mockImplementation(async (spec: { table: string; filters?: { col: string; value: unknown }[] }) => {
    if (spec.table !== 'job_items') throw new Error(`unexpected table ${spec.table}`);
    specs.push(spec);
    return { rows, total: rows.length };
  });
  queryOneMock.mockImplementation(async (table: string) => {
    if (table !== 'job_items') throw new Error(`unexpected table ${table}`);
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
  return render(<StageRunsBrowser />, { wrapper: Wrapper });
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

beforeEach(() => {
  queryTableMock.mockReset();
  queryOneMock.mockReset();
  queryAllMock.mockReset();
});

describe('<StageRunsBrowser>', () => {
  it('lists job_items rows with outcome as a StatusPill', async () => {
    mockApi([
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
    const { detailEq } = mockApi(
      [{ id: 1, entity_type: 'recipe', entity_id: 10, stage: 'parse-ingredients', code_version: 'v10', outcome: 'resolved', method: 'deterministic', cost_cents: 0, started_at: '2026-07-01T00:00:00Z', finished_at: null }],
      { id: 1, entity_type: 'recipe', entity_id: 10, stage: 'parse-ingredients', code_version: 'v10', outcome: 'resolved', method: 'deterministic', cost_cents: 0, started_at: '2026-07-01T00:00:00Z', finished_at: null, payload: { structured: 3 } },
    );
    renderBrowser(makeClient());
    const row = await within(await screen.findByRole('table')).findByRole('button');
    await userEvent.click(row);
    await waitFor(() => expect(detailEq).toHaveBeenCalledWith('job_items', [{ col: 'id', op: 'eq', value: 1 }]));
    expect(await screen.findByText(/structured/)).toBeInTheDocument();
  });

  it('applies the stage/outcome/version filters to the underlying query', async () => {
    const { listEqCalls } = mockApi([]);
    renderBrowser(makeClient());

    await userEvent.selectOptions(screen.getByLabelText('stage'), 'map-ingredient');
    await userEvent.selectOptions(screen.getByLabelText('outcome'), 'failed');
    await userEvent.type(screen.getByLabelText('version'), 'v2');

    await waitFor(() => {
      expect(listEqCalls()).toContainEqual(['stage', 'map-ingredient']);
      expect(listEqCalls()).toContainEqual(['outcome', 'failed']);
      expect(listEqCalls()).toContainEqual(['code_version', 'v2']);
    });
  });
});
