import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const apiMock = vi.fn();
vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  api: (...args: unknown[]) => apiMock(...args),
}));
import { ApiError } from '../api';

const useIsAdminMock = vi.fn();
vi.mock('../auth/useIsAdmin', () => ({ useIsAdmin: () => useIsAdminMock() }));

import { RecipeDetail } from './RecipeDetail';

// The recipe fetch resolves with `data`, or rejects with `error` (an ApiError
// for an HTTP failure). Any other call (the parsed-ingredients fetch) resolves
// to an empty list unless a test overrides it.
function mockSingleResponse(data: unknown, error: unknown = null) {
  apiMock.mockImplementation(async (path: string) => {
    if (/^\/api\/recipes\/\d+$/.test(path)) {
      if (error) throw error;
      return data;
    }
    return [];
  });
  return { api: apiMock };
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
    useIsAdminMock.mockReturnValue({ isAdmin: false, isLoading: false });
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
    mockSingleResponse(null, new ApiError(404, 'recipe not found'));
    renderAt('999');
    expect(await screen.findByRole('heading', { name: /recipe not found/i })).toBeInTheDocument();
  });

  it('renders ErrorPage on other fetch failures', async () => {
    mockSingleResponse(null, new ApiError(500, 'boom'));
    renderAt('1');
    expect(await screen.findByRole('heading', { name: /couldn't load/i })).toBeInTheDocument();
    expect(screen.getByText(/boom/i)).toBeInTheDocument();
  });

  it('links to the source URL with full URL as link text', async () => {
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
    const link = await screen.findByRole('link', {
      name: /view at https:\/\/example\.com\/x/i,
    });
    expect(link).toHaveAttribute('href', 'https://example.com/x');
  });

  it('shows the source host (not site name) in the byline', async () => {
    mockSingleResponse({
      id: 1,
      source_url: 'https://www.epicurious.com/recipes/food/views/new-york-sour',
      site: 'epicurious',
      name: 'New York Sour',
      author: null,
      image_url: null,
      jsonld: { name: 'New York Sour', author: 'Mary Frances Heck' },
    });
    renderAt('1');
    await screen.findByRole('heading', { name: /new york sour/i });
    expect(screen.getByText(/mary frances heck/i)).toHaveTextContent(
      /www\.epicurious\.com/i,
    );
    expect(screen.queryByText(/· epicurious$/)).not.toBeInTheDocument();
  });

  it('renders multiple instruction steps as an <ol>', async () => {
    mockSingleResponse({
      id: 1,
      source_url: 'https://x/y',
      site: 's',
      name: 'X',
      author: null,
      image_url: null,
      jsonld: {
        name: 'X',
        recipeInstructions: ['Stir.', 'Strain.'],
      },
    });
    const { container } = renderAt('1');
    await screen.findByRole('heading', { name: 'X' });
    const ol = container.querySelector('.recipe-detail__steps');
    expect(ol?.tagName).toBe('OL');
    expect(ol?.querySelectorAll('li')).toHaveLength(2);
  });

  it('renders a single instruction step as a paragraph (not <ol>)', async () => {
    mockSingleResponse({
      id: 1,
      source_url: 'https://x/y',
      site: 's',
      name: 'X',
      author: null,
      image_url: null,
      jsonld: {
        name: 'X',
        recipeInstructions: 'Combine everything in a shaker and strain.',
      },
    });
    const { container } = renderAt('1');
    await screen.findByText(/combine everything/i);
    expect(container.querySelector('.recipe-detail__steps')).toBeNull();
  });

  it('short-circuits to not-found for a non-numeric id without calling the API', async () => {
    mockSingleResponse(null);
    renderAt('abc');
    expect(
      await screen.findByRole('heading', { name: /recipe not found/i }),
    ).toBeInTheDocument();
    expect(apiMock).not.toHaveBeenCalled();
  });

  it('renders raw ingredient lines for a non-admin (no fetch of recipe_ingredients)', async () => {
    useIsAdminMock.mockReturnValue({ isAdmin: false, isLoading: false });
    mockSingleResponse({
      id: 1, source_url: 'https://x.test/r', site: 'x.test', name: 'Test',
      author: null, image_url: null,
      jsonld: {
        name: 'Test', recipeIngredient: ['2 oz gin', '1 oz lime'],
      },
    });
    renderAt('1');
    expect(await screen.findByText('2 oz gin')).toBeInTheDocument();
    expect(screen.getByText('1 oz lime')).toBeInTheDocument();
    // The parsed-ingredients endpoint is not called in non-admin mode.
    expect(apiMock).toHaveBeenCalledTimes(1);
    expect(apiMock).toHaveBeenCalledWith('/api/recipes/1');
  });

  it('fetches and renders parsed ingredients for an admin', async () => {
    useIsAdminMock.mockReturnValue({ isAdmin: true, isLoading: false });
    mockSingleResponse({
      id: 1, source_url: 'https://x.test/r', site: 'x.test', name: 'Test',
      author: null, image_url: null,
      jsonld: { name: 'Test', recipeIngredient: ['2 oz gin'] },
    });
    apiMock.mockImplementation(async (path: string) => {
      if (path === '/api/recipes/1') {
        return {
          id: 1, source_url: 'https://x.test/r', site: 'x.test', name: 'Test',
          author: null, image_url: null,
          jsonld: { name: 'Test', recipeIngredient: ['2 oz gin'] },
        };
      }
      if (path === '/api/recipes/1/ingredients') {
        return [{
          id: 17, position: 0, raw_text: '2 oz gin',
          amount: 2, amount_max: null, unit: 'oz',
          name: 'gin', modifiers: [],
          taxonomy_node: { id: 5, slug: 'gin', display_name: 'Gin', status: 'live' },
        }];
      }
      throw new Error(`unexpected ${path}`);
    });

    renderAt('1');
    expect(await screen.findByRole('link', { name: /gin/i })).toHaveAttribute(
      'href', '/taxonomy?node=gin',
    );
    expect(screen.getByText('2 oz')).toBeInTheDocument();
    expect(screen.getByText('#17')).toBeInTheDocument();
  });
});
