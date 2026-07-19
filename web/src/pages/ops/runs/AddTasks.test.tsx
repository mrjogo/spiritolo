import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const fromMock = vi.fn();
const rpcMock = vi.fn();
vi.mock('../../../supabase', () => ({
  supabase: {
    from: (table: string) => fromMock(table),
    rpc: (fn: string, args: unknown) => rpcMock(fn, args),
  },
}));

import { AddTasks } from './AddTasks';

const RUN = {
  id: 142,
  stage: 'map',
  state: 'draft',
  apply_mode: 'hold',
  llm_provider: 'deepseek',
  llm_model: 'deepseek-chat',
  task_count: 1102,
  flagged_count: 838,
  never_run_count: 231,
  failed_count: 33,
  cost_estimate_cents: 61,
  max_cost_cents: 150,
  created_at: '2026-07-18',
  created_by: 'admin@local.test',
};

const POOL_ROWS = [
  { entity_id: '1', title: 'Oaxaca Old Fashioned', source: 'diffordsguide', status: 'flagged', status_detail: 'flagged · 1 name', last_run_label: '#814 · Jul 12', total_count: 1139 },
  { entity_id: '2', title: 'Paper Plane', source: 'diffordsguide', status: 'flagged', status_detail: 'flagged · 2 names', last_run_label: '#814 · Jul 12', total_count: 1139 },
];

const FACETS = {
  status: { flagged: 1102, failed: 37, never_run: 1240 },
  source: { diffordsguide: 900, punch: 239 },
};

function installMocks() {
  fromMock.mockImplementation((table: string) => {
    if (table === 'runs') {
      return {
        select: () => ({
          eq: () => ({ maybeSingle: () => Promise.resolve({ data: RUN, error: null }) }),
        }),
      };
    }
    throw new Error(`unexpected table ${table}`);
  });
  rpcMock.mockImplementation((fn: string) => {
    if (fn === 'eligible_pool') return Promise.resolve({ data: POOL_ROWS, error: null });
    if (fn === 'eligible_pool_facets') return Promise.resolve({ data: FACETS, error: null });
    if (fn === 'add_run_items') return Promise.resolve({ data: 2, error: null });
    if (fn === 'add_run_items_by_filter') return Promise.resolve({ data: 1139, error: null });
    throw new Error(`unexpected rpc ${fn}`);
  });
}

function renderAt(path = '/ops/runs/142/add') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/ops/runs/:id/add" element={<AddTasks />} />
        <Route path="/ops/runs/:id" element={<div>run detail landing</div>} />
      </Routes>
    </MemoryRouter>,
    { wrapper: Wrapper },
  );
}

beforeEach(() => {
  fromMock.mockReset();
  rpcMock.mockReset();
  installMocks();
});

describe('<AddTasks>', () => {
  it('renders the eligible pool with its status detail', async () => {
    renderAt();
    expect(await screen.findByText('Oaxaca Old Fashioned')).toBeInTheDocument();
    expect(screen.getByText('flagged · 2 names')).toBeInTheDocument();
  });

  it('shows facet counts in the Status filter popover', async () => {
    renderAt();
    await screen.findByText('Oaxaca Old Fashioned');
    await userEvent.click(screen.getByRole('button', { name: /Status/ }));
    const popover = await screen.findByRole('dialog', { name: /Filter: status/i });
    // Every option listed with its count (OR-within-a-dimension multiselect).
    // Scoped to the popover: 1,102 also appears as the "in run" metric.
    const pop = within(popover);
    expect(pop.getByText('flagged')).toBeInTheDocument();
    expect(pop.getByText('1,102')).toBeInTheDocument();
    expect(pop.getByText('never run')).toBeInTheDocument();
    expect(pop.getByText('1,240')).toBeInTheDocument();
  });

  it('adds the explicit selection to the run and returns to the run', async () => {
    renderAt();
    await screen.findByText('Oaxaca Old Fashioned');

    await userEvent.click(screen.getByRole('checkbox', { name: 'select Oaxaca Old Fashioned' }));
    // Selection surfaces the add bar with the running count.
    const addBtn = await screen.findByRole('button', { name: /Add 1 to run/ });
    await userEvent.click(addBtn);

    await waitFor(() =>
      expect(rpcMock).toHaveBeenCalledWith(
        'add_run_items',
        expect.objectContaining({ job_id: 142, entity_type: 'recipe', entity_ids: ['1'] }),
      ),
    );
    // Navigates back to the run detail landing.
    expect(await screen.findByText('run detail landing')).toBeInTheDocument();
  });

  it('"Select all N matching" flips the count to the full matching total', async () => {
    renderAt();
    await screen.findByText('Oaxaca Old Fashioned');
    await userEvent.click(screen.getByRole('checkbox', { name: 'select Oaxaca Old Fashioned' }));
    await userEvent.click(screen.getByRole('button', { name: /Select all 1,139 matching/ }));
    expect(await screen.findByRole('button', { name: /Add 1,139 to run/ })).toBeInTheDocument();
  });
});
