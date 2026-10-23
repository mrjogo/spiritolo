import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
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

import { ExportsBrowser } from './ExportsBrowser';

interface ExportListRow {
  id: number;
  recipe_id: number;
  recipe_slug: string;
  recipe_ref: string;
  converter_version: string;
  exported_at: string;
}

interface MockConfig {
  exportListRows: ExportListRow[];
  exportDetail?: unknown;
  recipeHeader?: unknown;
  ingredientRows?: unknown[];
  stepRows?: unknown[];
  resolutionRows?: unknown[];
}

function mockApi(cfg: MockConfig) {
  queryTableMock.mockImplementation(async (spec: { table: string }) => {
    if (spec.table === 'recipe_exports') return { rows: cfg.exportListRows, total: cfg.exportListRows.length };
    throw new Error(`unexpected paged table ${spec.table}`);
  });
  queryOneMock.mockImplementation(async (table: string) => {
    if (table === 'recipe_exports') return cfg.exportDetail ?? null;
    if (table === 'recipes') return cfg.recipeHeader ?? null;
    throw new Error(`unexpected single table ${table}`);
  });
  queryAllMock.mockImplementation(async (table: string) => {
    if (table === 'recipe_ingredients') return cfg.ingredientRows ?? [];
    if (table === 'recipe_steps') return cfg.stepRows ?? [];
    if (table === 'ingredient_resolutions') return cfg.resolutionRows ?? [];
    throw new Error(`unexpected list table ${table}`);
  });
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
  queryTableMock.mockReset();
  queryOneMock.mockReset();
  queryAllMock.mockReset();
});

describe('<ExportsBrowser>', () => {
  it('lists frozen recipe_exports rows', async () => {
    mockApi({
      exportListRows: [
        { id: 1, recipe_id: 10, recipe_slug: 'old-fashioned', recipe_ref: 'com.spiritolo/old-fashioned:v1', converter_version: 'v1', exported_at: '2026-07-01T00:00:00Z' },
      ],
    });
    renderBrowser(makeClient());
    const table = await screen.findByRole('table');
    expect(await within(table).findByText('old-fashioned')).toBeInTheDocument();
  });

  it('selecting a frozen export shows its bundle JSON', async () => {
    mockApi({
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
    mockApi({
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
