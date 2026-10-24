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

import { ClustersBrowser } from './ClustersBrowser';

interface ClusterRow {
  cluster_key: string;
  canonical_name: string;
  recipe_count: number;
  source_count: number;
}

function mockApi(
  clusterRows: ClusterRow[],
  detailRow: unknown = null,
  memberRows: { id: number; name: string | null; site: string }[] = [],
) {
  queryTableMock.mockImplementation(async (spec: { table: string }) => {
    if (spec.table !== 'recipe_clusters') throw new Error(`unexpected table ${spec.table}`);
    return { rows: clusterRows, total: clusterRows.length };
  });
  queryOneMock.mockImplementation(async (table: string) => {
    if (table !== 'recipe_clusters') throw new Error(`unexpected table ${table}`);
    return detailRow;
  });
  const membersEqCalls: [string, unknown][] = [];
  queryAllMock.mockImplementation(async (table: string, opts: { filters?: { col: string; value: unknown }[] }) => {
    if (table !== 'recipes_public') throw new Error(`unexpected table ${table}`);
    for (const f of opts.filters ?? []) membersEqCalls.push([f.col, f.value]);
    return memberRows;
  });
  return { detailEq: queryOneMock, membersEqCalls };
}

function renderBrowser(client: QueryClient) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  }
  return render(<ClustersBrowser />, { wrapper: Wrapper });
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

beforeEach(() => {
  queryTableMock.mockReset();
  queryOneMock.mockReset();
  queryAllMock.mockReset();
});

describe('<ClustersBrowser>', () => {
  it('lists recipe_clusters rows with recipe/source counts', async () => {
    mockApi([
      { cluster_key: 'abc123', canonical_name: 'Old Fashioned', recipe_count: 4, source_count: 3 },
    ]);
    renderBrowser(makeClient());
    const table = await screen.findByRole('table');
    expect(await within(table).findByText('Old Fashioned')).toBeInTheDocument();
    expect(within(table).getByText('4')).toBeInTheDocument();
  });

  it('selecting a cluster shows its ingredient_set and member recipes', async () => {
    const { detailEq, membersEqCalls } = mockApi(
      [{ cluster_key: 'abc123', canonical_name: 'Old Fashioned', recipe_count: 2, source_count: 2 }],
      { cluster_key: 'abc123', canonical_name: 'Old Fashioned', recipe_count: 2, source_count: 2, ingredient_set: [{ slug: 'bourbon', role: 'spirit' }] },
      [{ id: 10, name: 'The Old Fashioned', site: 'punch' }],
    );
    renderBrowser(makeClient());
    const row = await within(await screen.findByRole('table')).findByRole('button');
    await userEvent.click(row);
    await waitFor(() => expect(detailEq).toHaveBeenCalledWith('recipe_clusters', [{ col: 'cluster_key', op: 'eq', value: 'abc123' }]));
    expect(await screen.findByText('"bourbon"')).toBeInTheDocument();
    expect(await screen.findByText(/The Old Fashioned/)).toBeInTheDocument();
    expect(membersEqCalls).toContainEqual(['cluster_id', 'abc123']);
  });
});
