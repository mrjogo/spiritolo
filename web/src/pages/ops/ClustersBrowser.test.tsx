import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const fromMock = vi.fn();
vi.mock('../../supabase', () => ({ supabase: { from: (table: string) => fromMock(table) } }));

import { ClustersBrowser } from './ClustersBrowser';

interface ClusterRow {
  cluster_key: string;
  canonical_name: string;
  recipe_count: number;
  source_count: number;
}

function mockSupabase(
  clusterRows: ClusterRow[],
  detailRow: unknown = null,
  memberRows: { id: number; name: string | null; site: string }[] = [],
) {
  const listEqCalls: [string, unknown][] = [];
  const range = vi.fn().mockResolvedValue({ data: clusterRows, count: clusterRows.length, error: null });
  const listChain: Record<string, unknown> = {};
  listChain.eq = vi.fn((col: string, value: unknown) => { listEqCalls.push([col, value]); return listChain; });
  listChain.order = vi.fn(() => ({ range }));

  const maybeSingle = vi.fn().mockResolvedValue({ data: detailRow, error: null });
  const detailEq = vi.fn(() => ({ maybeSingle }));

  const membersEqCalls: [string, unknown][] = [];
  const members = vi.fn().mockResolvedValue({ data: memberRows, error: null });

  fromMock.mockImplementation((table: string) => {
    if (table === 'recipe_clusters') {
      return {
        select: (_sel: string, opts?: { count?: string }) =>
          (opts && opts.count ? listChain : { eq: detailEq }),
      };
    }
    if (table === 'recipes_public') {
      return {
        select: () => ({
          eq: (col: string, value: unknown) => {
            membersEqCalls.push([col, value]);
            return members();
          },
        }),
      };
    }
    throw new Error(`unexpected table ${table}`);
  });

  return { listEqCalls, detailEq, membersEqCalls };
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
  fromMock.mockReset();
});

describe('<ClustersBrowser>', () => {
  it('lists recipe_clusters rows with recipe/source counts', async () => {
    mockSupabase([
      { cluster_key: 'abc123', canonical_name: 'Old Fashioned', recipe_count: 4, source_count: 3 },
    ]);
    renderBrowser(makeClient());
    const table = await screen.findByRole('table');
    expect(await within(table).findByText('Old Fashioned')).toBeInTheDocument();
    expect(within(table).getByText('4')).toBeInTheDocument();
  });

  it('selecting a cluster shows its ingredient_set and member recipes', async () => {
    const { detailEq, membersEqCalls } = mockSupabase(
      [{ cluster_key: 'abc123', canonical_name: 'Old Fashioned', recipe_count: 2, source_count: 2 }],
      { cluster_key: 'abc123', canonical_name: 'Old Fashioned', recipe_count: 2, source_count: 2, ingredient_set: [{ slug: 'bourbon', role: 'spirit' }] },
      [{ id: 10, name: 'The Old Fashioned', site: 'punch' }],
    );
    renderBrowser(makeClient());
    const row = await within(await screen.findByRole('table')).findByRole('button');
    await userEvent.click(row);
    await waitFor(() => expect(detailEq).toHaveBeenCalledWith('cluster_key', 'abc123'));
    expect(await screen.findByText('"bourbon"')).toBeInTheDocument();
    expect(await screen.findByText(/The Old Fashioned/)).toBeInTheDocument();
    expect(membersEqCalls).toContainEqual(['cluster_id', 'abc123']);
  });
});
