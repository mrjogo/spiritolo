import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

// Mock the supabase module BEFORE importing the component.
vi.mock('../supabase', () => ({ supabase: { from: vi.fn() } }));
import { supabase } from '../supabase';
import { RecipeList } from './RecipeList';

type Row = { id: number; site: string; name: string | null; image_url: string | null };

type OrChain = {
  or: ReturnType<typeof vi.fn>;
  order: ReturnType<typeof vi.fn>;
};

function makeChain(rows: Row[], count: number, error: unknown = null) {
  const range = vi.fn().mockResolvedValue({ data: rows, count, error });
  const order = vi.fn(() => ({ range }));
  const or: OrChain['or'] = vi.fn();
  or.mockReturnValue({ or, order });
  const select = vi.fn(() => ({ or, order }));
  (supabase.from as unknown as ReturnType<typeof vi.fn>).mockReturnValue({ select });
  return { range, order, or, select };
}

function mockRangeResponse(rows: Row[], count: number, error: unknown = null) {
  return makeChain(rows, count, error);
}

function mockRejection(message: string) {
  makeChain([], 0, { message });
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

  it('shows an empty-state message when loaded with zero rows', async () => {
    mockRangeResponse([], 0);
    render(
      <MemoryRouter>
        <RecipeList />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/no recipes yet/i)).toBeInTheDocument();
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

  it('renders pagination at both the top and bottom when there is more than one page', async () => {
    mockRangeResponse(
      Array.from({ length: 50 }, (_, i) => ({
        id: i + 1,
        site: 's',
        name: `R${i + 1}`,
        image_url: null,
      })),
      127,
    );
    const { container } = render(
      <MemoryRouter>
        <RecipeList />
      </MemoryRouter>,
    );
    await screen.findByText('R1');
    expect(container.querySelectorAll('.pagination')).toHaveLength(2);
    expect(screen.getAllByText('1–50 of 127')).toHaveLength(2);
  });

  it('orders results alphabetically by name with nulls last', async () => {
    const { order } = mockRangeResponse([], 0);
    render(
      <MemoryRouter>
        <RecipeList />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(order).toHaveBeenCalledWith('name', { nullsFirst: false }),
    );
  });

  it('renders a search input on the recipe list page', () => {
    mockRangeResponse([], 0);
    render(
      <MemoryRouter>
        <RecipeList />
      </MemoryRouter>,
    );
    expect(screen.getByRole('searchbox', { name: /search recipes/i })).toBeInTheDocument();
  });

  it('pre-fills the search input from the URL ?q=', () => {
    mockRangeResponse([], 0);
    render(
      <MemoryRouter initialEntries={['/?q=negroni']}>
        <RecipeList />
      </MemoryRouter>,
    );
    expect(screen.getByRole('searchbox', { name: /search recipes/i })).toHaveValue(
      'negroni',
    );
  });

  it('does not call .or() when q is empty', async () => {
    const { or, range } = mockRangeResponse([], 0);
    render(
      <MemoryRouter>
        <RecipeList />
      </MemoryRouter>,
    );
    await waitFor(() => expect(range).toHaveBeenCalled());
    expect(or).not.toHaveBeenCalled();
  });

  it('calls .or() once per term when q has one term', async () => {
    const { or } = mockRangeResponse([], 0);
    render(
      <MemoryRouter initialEntries={['/?q=negroni']}>
        <RecipeList />
      </MemoryRouter>,
    );
    await waitFor(() => expect(or).toHaveBeenCalledTimes(1));
    expect(or).toHaveBeenCalledWith(
      'name.ilike.*negroni*,jsonld->>recipeIngredient.ilike.*negroni*',
    );
  });

  it('calls .or() once per term when q has multiple terms', async () => {
    const { or } = mockRangeResponse([], 0);
    render(
      <MemoryRouter initialEntries={['/?q=gin%20lime']}>
        <RecipeList />
      </MemoryRouter>,
    );
    await waitFor(() => expect(or).toHaveBeenCalledTimes(2));
    expect(or).toHaveBeenNthCalledWith(
      1,
      'name.ilike.*gin*,jsonld->>recipeIngredient.ilike.*gin*',
    );
    expect(or).toHaveBeenNthCalledWith(
      2,
      'name.ilike.*lime*,jsonld->>recipeIngredient.ilike.*lime*',
    );
  });

  it('does not call .or() when q has only sub-3-char terms', async () => {
    const { or } = mockRangeResponse([], 0);
    render(
      <MemoryRouter initialEntries={['/?q=a%20b']}>
        <RecipeList />
      </MemoryRouter>,
    );
    await waitFor(() => expect(or).toHaveBeenCalledTimes(0));
  });

  it('updates the URL ?q= 250ms after typing stops, refetching with the new term', async () => {
    vi.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { or } = mockRangeResponse([], 0);
    render(
      <MemoryRouter initialEntries={['/']}>
        <RecipeList />
      </MemoryRouter>,
    );
    const box = await screen.findByRole('searchbox', { name: /search recipes/i });
    await user.type(box, 'neg');
    // Before the debounce fires, .or has NOT been called for "neg"
    expect(or).not.toHaveBeenCalled();
    vi.advanceTimersByTime(250);
    await waitFor(() => expect(or).toHaveBeenCalledTimes(1));
    expect(or).toHaveBeenCalledWith(
      'name.ilike.*neg*,jsonld->>recipeIngredient.ilike.*neg*',
    );
    vi.useRealTimers();
  });

  it('coalesces consecutive keystrokes into a single URL write', async () => {
    vi.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { or } = mockRangeResponse([], 0);
    render(
      <MemoryRouter initialEntries={['/']}>
        <RecipeList />
      </MemoryRouter>,
    );
    const box = await screen.findByRole('searchbox', { name: /search recipes/i });
    await user.type(box, 'negroni');
    // Many keystrokes typed; debounce hasn't fired
    vi.advanceTimersByTime(100);
    expect(or).not.toHaveBeenCalled();
    vi.advanceTimersByTime(250);
    await waitFor(() => expect(or).toHaveBeenCalledTimes(1));
    expect(or).toHaveBeenCalledWith(
      'name.ilike.*negroni*,jsonld->>recipeIngredient.ilike.*negroni*',
    );
    vi.useRealTimers();
  });
});
