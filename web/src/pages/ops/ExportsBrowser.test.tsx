import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const fromMock = vi.fn();
vi.mock('../../supabase', () => ({ supabase: { from: (table: string) => fromMock(table) } }));

import { ExportsBrowser } from './ExportsBrowser';

interface ExportListRow {
  id: number;
  recipe_id: number;
  recipe_slug: string;
  recipe_ref: string;
  converter_version: string;
  exported_at: string;
}

function mockList(rows: ExportListRow[]) {
  const range = vi.fn().mockResolvedValue({ data: rows, count: rows.length, error: null });
  const chain: Record<string, unknown> = {};
  chain.order = vi.fn(() => ({ range }));
  return chain;
}

function singleEq(row: unknown) {
  const maybeSingle = vi.fn().mockResolvedValue({ data: row, error: null });
  const eq = vi.fn(() => ({ maybeSingle }));
  return { eq };
}

function listByEq(rows: unknown[]) {
  const order = vi.fn().mockResolvedValue({ data: rows, error: null });
  const eq = vi.fn(() => ({ order }));
  return { eq };
}

function listByIn(rows: unknown[]) {
  return { in: vi.fn().mockResolvedValue({ data: rows, error: null }) };
}

interface MockConfig {
  exportListRows: ExportListRow[];
  exportDetail?: unknown;
  recipeHeader?: unknown;
  ingredientRows?: unknown[];
  stepRows?: unknown[];
  resolutionRows?: unknown[];
}

function mockSupabase(cfg: MockConfig) {
  const listChain = mockList(cfg.exportListRows);
  const detail = singleEq(cfg.exportDetail ?? null);
  const header = singleEq(cfg.recipeHeader ?? null);
  const ingredients = listByEq(cfg.ingredientRows ?? []);
  const steps = listByEq(cfg.stepRows ?? []);
  const resolutions = listByIn(cfg.resolutionRows ?? []);

  fromMock.mockImplementation((table: string) => {
    if (table === 'recipe_exports') {
      // First select() (no args tracked here) always used for the paged
      // list AND for looking up a single export row by id — dispatch by
      // presence of a `.order` vs `.eq` call shape via a shared object.
      return {
        select: vi.fn(() => ({ ...listChain, eq: detail.eq })),
      };
    }
    if (table === 'recipes') {
      return { select: vi.fn(() => ({ eq: header.eq })) };
    }
    if (table === 'recipe_ingredients') {
      return { select: vi.fn(() => ({ eq: ingredients.eq })) };
    }
    if (table === 'recipe_steps') {
      return { select: vi.fn(() => ({ eq: steps.eq })) };
    }
    if (table === 'ingredient_resolutions') {
      return { select: vi.fn(() => ({ in: resolutions.in })) };
    }
    throw new Error(`unexpected table ${table}`);
  });

  return { listChain, detail, header, ingredients, steps, resolutions };
}

function renderBrowser(client: QueryClient) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  }
  return render(<ExportsBrowser />, { wrapper: Wrapper });
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

beforeEach(() => {
  fromMock.mockReset();
});

describe('<ExportsBrowser>', () => {
  it('lists frozen recipe_exports rows', async () => {
    mockSupabase({
      exportListRows: [
        { id: 1, recipe_id: 10, recipe_slug: 'old-fashioned', recipe_ref: 'com.spiritolo/old-fashioned:v1', converter_version: 'v1', exported_at: '2026-07-01T00:00:00Z' },
      ],
    });
    renderBrowser(makeClient());
    const table = await screen.findByRole('table');
    expect(await within(table).findByText('old-fashioned')).toBeInTheDocument();
  });

  it('selecting a frozen export shows its bundle JSON', async () => {
    mockSupabase({
      exportListRows: [
        { id: 1, recipe_id: 10, recipe_slug: 'old-fashioned', recipe_ref: 'com.spiritolo/old-fashioned:v1', converter_version: 'v1', exported_at: '2026-07-01T00:00:00Z' },
      ],
      exportDetail: {
        id: 1, recipe_id: 10, recipe_slug: 'old-fashioned', recipe_ref: 'com.spiritolo/old-fashioned:v1',
        converter_version: 'v1', exported_at: '2026-07-01T00:00:00Z',
        bundle: { recipe: { id: 'com.spiritolo/old-fashioned:v1', title: 'Old Fashioned' }, verbs: [], meta: { slug: 'old-fashioned' } },
      },
    });
    renderBrowser(makeClient());
    // Scoped to the table: the preview panel's own "Preview" button also
    // has role="button", and would match before the row has loaded.
    const table = await screen.findByRole('table');
    const row = await within(table).findByRole('button');
    await userEvent.click(row);
    expect(await screen.findByText('"Old Fashioned"')).toBeInTheDocument();
  });

  it('generates an unvalidated on-demand preview for a recipe id typed into the preview panel', async () => {
    mockSupabase({
      exportListRows: [],
      recipeHeader: {
        id: 42, title: 'Negroni', canonical_name: 'negroni', recipe_slug: null,
        source_url: 'https://ex.test/n', equipment: [],
      },
      ingredientRows: [
        { name: 'Gin', amount: 1, amount_max: null, unit: 'oz' },
        { name: 'Mystery Amaro', amount: 1, amount_max: null, unit: 'oz' },
      ],
      stepRows: [],
      resolutionRows: [{ normalized_name: 'gin', taxonomy_slug: 'gin' }],
    });
    renderBrowser(makeClient());

    await userEvent.type(screen.getByLabelText(/recipe id/i), '42');
    await userEvent.click(screen.getByRole('button', { name: /preview/i }));

    expect(await screen.findByText('"com.spiritolo/negroni:v1"')).toBeInTheDocument();
    expect(await screen.findByText(/1 unresolved ingredient/i)).toBeInTheDocument();
  });
});
