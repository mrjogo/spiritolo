import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

const apiMock = vi.fn();
vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  api: (...args: unknown[]) => apiMock(...args),
}));
import { RecipeList } from './RecipeList';

type Row = { id: number; site: string; name: string | null; image_url: string | null };

function mockPage(rows: Row[], total: number) {
  apiMock.mockResolvedValue({ rows, total });
}

function mockRejection(message: string) {
  apiMock.mockRejectedValue(new Error(message));
}

function requestedUrl(): URL {
  const path = apiMock.mock.calls.at(-1)?.[0] as string;
  return new URL(path, 'http://test');
}

describe('<RecipeList>', () => {
  beforeEach(() => {
    apiMock.mockReset();
  });

  it('shows a loading state initially', () => {
    mockPage([], 0);
    render(<MemoryRouter><RecipeList /></MemoryRouter>);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it('shows an empty-state message when loaded with zero rows', async () => {
    mockPage([], 0);
    render(<MemoryRouter><RecipeList /></MemoryRouter>);
    expect(await screen.findByText(/no recipes yet/i)).toBeInTheDocument();
  });

  it('renders rows after loading', async () => {
    mockPage(
      [
        { id: 1, site: 'diffordsguide', name: 'Old Fashioned', image_url: null },
        { id: 2, site: 'diffordsguide', name: 'Martini', image_url: 'https://x/m.jpg' },
      ],
      2,
    );
    render(<MemoryRouter><RecipeList /></MemoryRouter>);
    expect(await screen.findByText('Old Fashioned')).toBeInTheDocument();
    expect(screen.getByText('Martini')).toBeInTheDocument();
  });

  it('renders an error block on fetch failure', async () => {
    mockRejection('db unreachable');
    render(<MemoryRouter><RecipeList /></MemoryRouter>);
    await waitFor(() => {
      expect(screen.getByText(/couldn't load recipes/i)).toBeInTheDocument();
      expect(screen.getByText(/db unreachable/i)).toBeInTheDocument();
    });
  });

  it('links each item to /recipes/:id', async () => {
    mockPage([{ id: 42, site: 's', name: 'A', image_url: null }], 1);
    render(<MemoryRouter><RecipeList /></MemoryRouter>);
    const link = await screen.findByRole('link', { name: /a/i });
    expect(link).toHaveAttribute('href', '/recipes/42');
  });

  it('requests page 1 with the page size', async () => {
    mockPage([], 0);
    render(<MemoryRouter><RecipeList /></MemoryRouter>);
    await waitFor(() => expect(apiMock).toHaveBeenCalled());
    const url = requestedUrl();
    expect(url.pathname).toBe('/api/recipes');
    expect(url.searchParams.get('page')).toBe('1');
    expect(url.searchParams.get('page_size')).toBe('50');
    expect(url.searchParams.has('q')).toBe(false);
  });

  it('requests ?page=3 when the URL says so', async () => {
    mockPage([], 0);
    render(<MemoryRouter initialEntries={['/?page=3']}><RecipeList /></MemoryRouter>);
    await waitFor(() => expect(apiMock).toHaveBeenCalled());
    expect(requestedUrl().searchParams.get('page')).toBe('3');
  });

  it('renders pagination at both the top and bottom when there is more than one page', async () => {
    mockPage(
      Array.from({ length: 50 }, (_, i) => ({ id: i + 1, site: 's', name: `R${i + 1}`, image_url: null })),
      127,
    );
    const { container } = render(<MemoryRouter><RecipeList /></MemoryRouter>);
    await screen.findByText('R1');
    expect(container.querySelectorAll('.pagination')).toHaveLength(2);
    expect(screen.getAllByText('1–50 of 127')).toHaveLength(2);
  });

  it('renders a search input on the recipe list page', () => {
    mockPage([], 0);
    render(<MemoryRouter><RecipeList /></MemoryRouter>);
    expect(screen.getByRole('searchbox', { name: /search recipes/i })).toBeInTheDocument();
  });

  it('pre-fills the search input from the URL ?q= and sends it to the API', async () => {
    mockPage([], 0);
    render(<MemoryRouter initialEntries={['/?q=negroni']}><RecipeList /></MemoryRouter>);
    expect(screen.getByRole('searchbox', { name: /search recipes/i })).toHaveValue('negroni');
    await waitFor(() => expect(apiMock).toHaveBeenCalled());
    expect(requestedUrl().searchParams.get('q')).toBe('negroni');
  });

  it('shows a no-match message for a search with zero results', async () => {
    mockPage([], 0);
    render(<MemoryRouter initialEntries={['/?q=zzz']}><RecipeList /></MemoryRouter>);
    expect(await screen.findByText(/no recipes match "zzz"/i)).toBeInTheDocument();
  });

  it('debounces typing into the URL and refetches on page 1', async () => {
    mockPage([], 0);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={['/?page=2']}><RecipeList /></MemoryRouter>);
    await waitFor(() => expect(apiMock).toHaveBeenCalled());
    await user.type(screen.getByRole('searchbox', { name: /search recipes/i }), 'gin');
    await waitFor(() => {
      const url = requestedUrl();
      expect(url.searchParams.get('q')).toBe('gin');
      expect(url.searchParams.get('page')).toBe('1');
    });
  });
});
