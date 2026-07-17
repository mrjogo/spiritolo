import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const fromMock = vi.fn();
vi.mock('../../supabase', () => ({ supabase: { from: (table: string) => fromMock(table) } }));

import { RecipesBrowser } from './RecipesBrowser';

interface RecipeListItem {
  id: number;
  source_url: string;
  site: string;
  name: string | null;
  cluster_id: string | null;
}

function mockList(rows: RecipeListItem[]) {
  const range = vi.fn().mockResolvedValue({ data: rows, count: rows.length, error: null });
  const chain: Record<string, unknown> = {};
  chain.eq = vi.fn(() => chain);
  chain.ilike = vi.fn(() => chain);
  chain.order = vi.fn(() => ({ range }));
  return chain;
}

function singleEq(row: unknown) {
  const maybeSingle = vi.fn().mockResolvedValue({ data: row, error: null });
  const eq = vi.fn(() => ({ maybeSingle }));
  return { eq, maybeSingle };
}

function listByEq(rows: unknown[]) {
  const order = vi.fn().mockResolvedValue({ data: rows, error: null });
  const eq = vi.fn(() => ({ order }));
  return { eq, order };
}

function listByIn(rows: unknown[]) {
  const inFn = vi.fn().mockResolvedValue({ data: rows, error: null });
  return { in: inFn };
}

interface MockConfig {
  listRows: RecipeListItem[];
  recipeDetail?: unknown;
  ingredientRows?: unknown[];
  resolutionRows?: unknown[];
  clusterRow?: unknown;
  exportRows?: unknown[];
}

function mockSupabase(cfg: MockConfig) {
  const listChain = mockList(cfg.listRows);
  const recipeDetail = singleEq(cfg.recipeDetail ?? null);
  const ingredients = listByEq(cfg.ingredientRows ?? []);
  const resolutions = listByIn(cfg.resolutionRows ?? []);
  const cluster = singleEq(cfg.clusterRow ?? null);
  const exports = listByEq(cfg.exportRows ?? []);

  fromMock.mockImplementation((table: string) => {
    if (table === 'recipes_public') {
      return { select: vi.fn(() => listChain) };
    }
    if (table === 'recipes') {
      return { select: vi.fn(() => ({ eq: recipeDetail.eq })) };
    }
    if (table === 'recipe_ingredients') {
      return { select: vi.fn(() => ({ eq: ingredients.eq })) };
    }
    if (table === 'ingredient_resolutions') {
      return { select: vi.fn(() => ({ in: resolutions.in })) };
    }
    if (table === 'recipe_clusters') {
      return { select: vi.fn(() => ({ eq: cluster.eq })) };
    }
    if (table === 'recipe_exports') {
      return { select: vi.fn(() => ({ eq: exports.eq })) };
    }
    throw new Error(`unexpected table ${table}`);
  });

  return { listChain, recipeDetail, ingredients, resolutions, cluster, exports };
}

function renderBrowser(client: QueryClient) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  }
  return render(<RecipesBrowser />, { wrapper: Wrapper });
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

beforeEach(() => {
  fromMock.mockReset();
});

describe('<RecipesBrowser>', () => {
  it('lists recipes_public rows', async () => {
    mockSupabase({
      listRows: [{ id: 1, source_url: 'https://ex.test/a', site: 'punch', name: 'Old Fashioned', cluster_id: null }],
    });
    renderBrowser(makeClient());
    const table = await screen.findByRole('table');
    expect(await within(table).findByText('Old Fashioned')).toBeInTheDocument();
  });

  it('drills from raw source through parsed ingredients, resolution, cluster, and export', async () => {
    mockSupabase({
      listRows: [{ id: 1, source_url: 'https://ex.test/a', site: 'punch', name: 'Old Fashioned', cluster_id: 'abc123' }],
      recipeDetail: {
        id: 1, source_url: 'https://ex.test/a', site: 'punch', title: 'Old Fashioned',
        canonical_name: 'old fashioned', cluster_id: 'abc123', recipe_slug: 'old-fashioned',
        source: { '@type': 'Recipe', name: 'Old Fashioned' },
      },
      ingredientRows: [
        { id: 10, position: 0, name: 'Bourbon', amount: 2, amount_max: null, unit: 'oz', raw_text: '2 oz bourbon' },
      ],
      resolutionRows: [{ normalized_name: 'bourbon', taxonomy_slug: 'bourbon' }],
      clusterRow: { cluster_key: 'abc123', canonical_name: 'Old Fashioned', recipe_count: 3, source_count: 2 },
      exportRows: [{ recipe_ref: 'com.spiritolo/old-fashioned:v1', converter_version: 'v1', exported_at: '2026-07-01T00:00:00Z' }],
    });
    renderBrowser(makeClient());
    const row = await within(await screen.findByRole('table')).findByRole('button');
    await userEvent.click(row);

    // Raw source JSON-LD is shown via JsonView.
    expect(await screen.findByText('"Recipe"')).toBeInTheDocument();
    // Parsed ingredient row, including its resolved taxonomy slug.
    expect(await screen.findByText(/2 oz bourbon/)).toBeInTheDocument();
    // the resolved slug is a cross-link to the taxonomy node
    expect(await screen.findByRole('link', { name: 'bourbon' })).toBeInTheDocument();
    // Cluster identity — scoped to the detail pane, since the list's own
    // "cluster" column cell also renders the same cluster_id text.
    const detailPane = document.querySelector('.detail-pane') as HTMLElement;
    expect(await within(detailPane).findByText(/abc123/)).toBeInTheDocument();
    // Export.
    expect(await screen.findByText(/com\.spiritolo\/old-fashioned:v1/)).toBeInTheDocument();
  });

  it('shows an honest not-yet-clustered / not-yet-exported state when those stages have not run', async () => {
    mockSupabase({
      listRows: [{ id: 1, source_url: 'https://ex.test/a', site: 'punch', name: 'Old Fashioned', cluster_id: null }],
      recipeDetail: {
        id: 1, source_url: 'https://ex.test/a', site: 'punch', title: 'Old Fashioned',
        canonical_name: null, cluster_id: null, recipe_slug: null, source: {},
      },
      ingredientRows: [],
      exportRows: [],
    });
    renderBrowser(makeClient());
    const row = await within(await screen.findByRole('table')).findByRole('button');
    await userEvent.click(row);
    expect(await screen.findByText(/not yet clustered/i)).toBeInTheDocument();
    expect(await screen.findByText(/not yet exported/i)).toBeInTheDocument();
  });

  it('filters the list by site and free text via FilterBar', async () => {
    const { listChain } = mockSupabase({ listRows: [] });
    renderBrowser(makeClient());
    await userEvent.type(screen.getByLabelText('filter text'), 'negroni');
    await waitFor(() => expect(listChain.ilike).toHaveBeenCalledWith('name', '%negroni%'));
  });
});
