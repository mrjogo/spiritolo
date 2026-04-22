import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// Mock the supabase module BEFORE importing the component.
vi.mock('../supabase', () => ({ supabase: { from: vi.fn() } }));
import { supabase } from '../supabase';
import { RecipeList } from './RecipeList';

type Row = { id: number; site: string; name: string | null; image_url: string | null };

function mockRangeResponse(rows: Row[], count: number, error: unknown = null) {
  const range = vi.fn().mockResolvedValue({ data: rows, count, error });
  const order = vi.fn(() => ({ range }));
  const select = vi.fn(() => ({ order }));
  (supabase.from as unknown as ReturnType<typeof vi.fn>).mockReturnValue({ select });
  return { range, order, select };
}

function mockRejection(message: string) {
  const range = vi.fn().mockResolvedValue({ data: null, count: null, error: { message } });
  const order = vi.fn(() => ({ range }));
  const select = vi.fn(() => ({ order }));
  (supabase.from as unknown as ReturnType<typeof vi.fn>).mockReturnValue({ select });
}

describe('<RecipeList>', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows a loading state initially', () => {
    mockRangeResponse([], 0);
    render(
      <MemoryRouter>
        <RecipeList />
      </MemoryRouter>,
    );
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it('renders rows after loading', async () => {
    mockRangeResponse(
      [
        { id: 1, site: 'diffordsguide', name: 'Old Fashioned', image_url: null },
        { id: 2, site: 'diffordsguide', name: 'Martini', image_url: 'https://x/m.jpg' },
      ],
      2,
    );
    render(
      <MemoryRouter>
        <RecipeList />
      </MemoryRouter>,
    );
    expect(await screen.findByText('Old Fashioned')).toBeInTheDocument();
    expect(screen.getByText('Martini')).toBeInTheDocument();
  });

  it('renders an error block on fetch failure', async () => {
    mockRejection('db unreachable');
    render(
      <MemoryRouter>
        <RecipeList />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText(/couldn't load recipes/i)).toBeInTheDocument();
      expect(screen.getByText(/db unreachable/i)).toBeInTheDocument();
    });
  });

  it('links each item to /recipes/:id', async () => {
    mockRangeResponse([{ id: 42, site: 's', name: 'A', image_url: null }], 1);
    render(
      <MemoryRouter>
        <RecipeList />
      </MemoryRouter>,
    );
    const link = await screen.findByRole('link', { name: /a/i });
    expect(link).toHaveAttribute('href', '/recipes/42');
  });

  it('requests the correct range for page 1 (0..49)', async () => {
    const { range } = mockRangeResponse([], 0);
    render(
      <MemoryRouter>
        <RecipeList />
      </MemoryRouter>,
    );
    await waitFor(() => expect(range).toHaveBeenCalledWith(0, 49));
  });

  it('requests the correct range for ?page=3 (100..149)', async () => {
    const { range } = mockRangeResponse([], 0);
    render(
      <MemoryRouter initialEntries={['/?page=3']}>
        <RecipeList />
      </MemoryRouter>,
    );
    await waitFor(() => expect(range).toHaveBeenCalledWith(100, 149));
  });
});
