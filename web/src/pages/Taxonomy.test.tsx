import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../supabase', () => ({ supabase: { from: vi.fn() } }));
import { supabase } from '../supabase';
import { Taxonomy } from './Taxonomy';

type Row = {
  id: number;
  slug: string;
  display_name: string;
  role: string | null;
  role_default: string | null;
  is_cluster_node: boolean;
  is_defining_garnish: boolean;
  parent_ids: number[];
  child_ids: number[];
  aliases: string[];
  recipe_count: number;
};

function mockTaxonomyResponse(rows: Row[], error: unknown = null) {
  const select = vi.fn().mockResolvedValue({ data: rows, error });
  (supabase.from as unknown as ReturnType<typeof vi.fn>).mockReturnValue({ select });
  return { select };
}

function row(slug: string, overrides: Partial<Row> = {}): Row {
  return {
    id: Math.floor(Math.random() * 1_000_000),
    slug,
    display_name: slug,
    role: null,
    role_default: 'substance',
    is_cluster_node: false,
    is_defining_garnish: false,
    parent_ids: [],
    child_ids: [],
    aliases: [],
    recipe_count: 0,
    ...overrides,
  };
}

describe('<Taxonomy>', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows a loading state initially', () => {
    mockTaxonomyResponse([]);
    render(
      <MemoryRouter>
        <Taxonomy />
      </MemoryRouter>,
    );
    expect(screen.getByText(/loading taxonomy/i)).toBeInTheDocument();
  });

  it('shows an error state when the fetch fails', async () => {
    mockTaxonomyResponse([], { message: 'db unreachable' });
    render(
      <MemoryRouter>
        <Taxonomy />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/db unreachable/i)).toBeInTheDocument();
  });

  it('shows the loaded state with node count', async () => {
    mockTaxonomyResponse([row('whiskey'), row('gin'), row('rum')]);
    render(
      <MemoryRouter>
        <Taxonomy />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/3 nodes/i)).toBeInTheDocument();
  });
});
