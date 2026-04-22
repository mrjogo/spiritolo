import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('../supabase', () => ({ supabase: { from: vi.fn() } }));
import { supabase } from '../supabase';
import { RecipeDetail } from './RecipeDetail';

function mockSingleResponse(data: unknown, error: unknown = null) {
  const single = vi.fn().mockResolvedValue({ data, error });
  const eq = vi.fn(() => ({ single }));
  const select = vi.fn(() => ({ eq }));
  (supabase.from as unknown as ReturnType<typeof vi.fn>).mockReturnValue({ select });
  return { single, eq, select };
}

function renderAt(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/recipes/${id}`]}>
      <Routes>
        <Route path="/recipes/:id" element={<RecipeDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('<RecipeDetail>', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows loading initially', () => {
    mockSingleResponse(null);
    renderAt('1');
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it('renders the normalized recipe on success', async () => {
    mockSingleResponse({
      id: 1,
      source_url: 'https://x/y',
      site: 'diffordsguide',
      name: 'Gin Martini',
      author: 'Jerry Thomas',
      image_url: null,
      jsonld: {
        name: 'Gin Martini',
        recipeIngredient: ['2 oz gin', '1 oz vermouth'],
        recipeInstructions: [{ '@type': 'HowToStep', text: 'Stir.' }],
      },
    });
    renderAt('1');
    expect(await screen.findByRole('heading', { name: 'Gin Martini' })).toBeInTheDocument();
    expect(screen.getByText('2 oz gin')).toBeInTheDocument();
    expect(screen.getByText('Stir.')).toBeInTheDocument();
  });

  it('renders ErrorPage when the recipe is missing', async () => {
    mockSingleResponse(null, { code: 'PGRST116', message: 'no rows' });
    renderAt('999');
    expect(await screen.findByRole('heading', { name: /recipe not found/i })).toBeInTheDocument();
  });

  it('renders ErrorPage on other fetch failures', async () => {
    mockSingleResponse(null, { code: 'OTHER', message: 'boom' });
    renderAt('1');
    expect(await screen.findByRole('heading', { name: /couldn't load/i })).toBeInTheDocument();
    expect(screen.getByText(/boom/i)).toBeInTheDocument();
  });

  it('links to the source URL', async () => {
    mockSingleResponse({
      id: 1,
      source_url: 'https://example.com/x',
      site: 's',
      name: 'X',
      author: null,
      image_url: null,
      jsonld: { name: 'X' },
    });
    renderAt('1');
    const link = await screen.findByRole('link', { name: /view on example\.com/i });
    expect(link).toHaveAttribute('href', 'https://example.com/x');
  });

  it('short-circuits to not-found for a non-numeric id without hitting Supabase', async () => {
    const { select } = mockSingleResponse(null);
    renderAt('abc');
    expect(
      await screen.findByRole('heading', { name: /recipe not found/i }),
    ).toBeInTheDocument();
    expect(select).not.toHaveBeenCalled();
  });
});
