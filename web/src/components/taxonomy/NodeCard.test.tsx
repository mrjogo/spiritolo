import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { NodeCard } from './NodeCard';
import type { TaxonomyNode } from './shapeData';

const fromMock = vi.fn();
vi.mock('../../supabase', () => ({ supabase: { from: (table: string) => fromMock(table) } }));

beforeEach(() => {
  fromMock.mockReset();
  // Default: return a chainable mock that never resolves (safe for tests that don't care about recipes).
  const neverResolve = vi.fn().mockReturnValue(new Promise(() => {}));
  fromMock.mockReturnValue({
    select: vi.fn(() => ({ eq: vi.fn(() => ({ order: neverResolve })) })),
  });
});

function renderCard(node: Parameters<typeof NodeCard>[0]['node'], mode: 'pinned' | 'hover' = 'pinned', onDismiss: () => void = () => {}) {
  return render(
    <MemoryRouter>
      <NodeCard node={node} mode={mode} onDismiss={onDismiss} />
    </MemoryRouter>,
  );
}

const node: TaxonomyNode = {
  id: 1, slug: 'rye_whiskey', display_name: 'Rye Whiskey',
  node_kind: 'expression', default_role: 'modifier',
  is_cluster_node: true, is_defining_garnish: false,
  parent_ids: [10, 11], child_ids: [20, 21],
  aliases: ['rye', 'rye whisky'], recipe_count: 47,
  labelW: 60, labelH: 11,
};

describe('<NodeCard>', () => {
  it('renders the node properties with the renamed labels', () => {
    renderCard(node);
    expect(screen.getByText('RYE WHISKEY')).toBeInTheDocument();
    expect(screen.getByText(/rye, rye whisky/)).toBeInTheDocument();
    expect(screen.getByText(/node kind/i)).toBeInTheDocument();
    expect(screen.getByText(/default ingredient role/i)).toBeInTheDocument();
    expect(screen.getByText(/clustering node/i)).toBeInTheDocument();
    // recipe count appears as "(47)" in the RECIPES heading
    expect(screen.getByText(/RECIPES/)).toBeInTheDocument();
    expect(screen.getByText(/\(47\)/)).toBeInTheDocument();
    // ID row exposes the database id
    expect(screen.getByText(/^ID$/)).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
  });

  it('shows the X button only in pinned mode and dismisses on click', async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    const { rerender } = render(
      <MemoryRouter>
        <NodeCard node={node} mode="pinned" onDismiss={onDismiss} />
      </MemoryRouter>,
    );
    const close = screen.getByRole('button', { name: /close/i });
    await user.click(close);
    expect(onDismiss).toHaveBeenCalled();

    rerender(
      <MemoryRouter>
        <NodeCard node={node} mode="hover" onDismiss={onDismiss} />
      </MemoryRouter>,
    );
    expect(screen.queryByRole('button', { name: /close/i })).toBeNull();
  });

  it('calls onDismiss when Escape is pressed in pinned mode', async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    renderCard(node, 'pinned', onDismiss);
    await user.keyboard('{Escape}');
    expect(onDismiss).toHaveBeenCalled();
  });

  it('does NOT call onDismiss on Escape in hover mode', async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    renderCard(node, 'hover', onDismiss);
    await user.keyboard('{Escape}');
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it('does not fetch recipes when recipe_count is 0', async () => {
    const zeroNode: TaxonomyNode = {
      id: 1, slug: 'gin', display_name: 'Gin',
      node_kind: null, default_role: 'base_spirit',
      is_cluster_node: true, is_defining_garnish: false,
      parent_ids: [], child_ids: [], aliases: [],
      recipe_count: 0, labelW: 10, labelH: 11,
    };
    renderCard(zeroNode);
    expect(fromMock).not.toHaveBeenCalled();
    // The RECIPES section shows '—' when count is 0
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  it('fetches and renders linked recipe list when recipe_count > 0', async () => {
    const recipeNode: TaxonomyNode = {
      id: 1, slug: 'gin', display_name: 'Gin',
      node_kind: null, default_role: 'base_spirit',
      is_cluster_node: true, is_defining_garnish: false,
      parent_ids: [], child_ids: [], aliases: [],
      recipe_count: 2, labelW: 10, labelH: 11,
    };
    const eq = vi.fn(() => ({
      order: vi.fn().mockResolvedValue({
        data: [
          { recipe_id: 10, recipes: { id: 10, name: 'Negroni', site: 'punchdrink.com' } },
          { recipe_id: 11, recipes: { id: 11, name: 'Boulevardier', site: 'imbibemagazine.com' } },
        ],
        error: null,
      }),
    }));
    fromMock.mockReturnValue({ select: vi.fn(() => ({ eq })) });

    renderCard(recipeNode);
    expect(await screen.findByRole('link', { name: /negroni/i })).toHaveAttribute(
      'href', '/recipes/10',
    );
    expect(screen.getByRole('link', { name: /boulevardier/i })).toHaveAttribute(
      'href', '/recipes/11',
    );
  });

  it('dedupes recipes by id when a node appears in multiple positions', async () => {
    const dedupNode: TaxonomyNode = {
      id: 1, slug: 'gin', display_name: 'Gin',
      node_kind: null, default_role: 'base_spirit',
      is_cluster_node: true, is_defining_garnish: false,
      parent_ids: [], child_ids: [], aliases: [],
      recipe_count: 1, labelW: 10, labelH: 11,
    };
    fromMock.mockReturnValue({
      select: vi.fn(() => ({
        eq: vi.fn(() => ({
          order: vi.fn().mockResolvedValue({
            data: [
              { recipe_id: 10, recipes: { id: 10, name: 'Negroni', site: 'punchdrink.com' } },
              { recipe_id: 10, recipes: { id: 10, name: 'Negroni', site: 'punchdrink.com' } },
            ],
            error: null,
          }),
        })),
      })),
    });
    renderCard(dedupNode);
    const links = await screen.findAllByRole('link', { name: /negroni/i });
    expect(links).toHaveLength(1);
  });
});

function makeNode(over: Partial<TaxonomyNode> = {}): TaxonomyNode {
  return {
    id: 42, slug: 'campari', display_name: 'Campari',
    node_kind: 'brand', default_role: 'modifier',
    is_cluster_node: true, is_defining_garnish: false,
    parent_ids: [17, 84], child_ids: [], aliases: ['campari aperitivo'],
    recipe_count: 0,
    labelW: 60, labelH: 11,
    ...over,
  };
}

describe('NodeCard — pinned mode editing', () => {
  it('renders PARENTS section with each parent name #id', () => {
    render(
      <MemoryRouter>
        <NodeCard
          node={makeNode()}
          mode="pinned"
          onDismiss={vi.fn()}
          onEditField={vi.fn()}
          onEditParents={vi.fn()}
          onDelete={vi.fn()}
          parentLookup={new Map([
            [17, { id: 17, display_name: 'Amari' }],
            [84, { id: 84, display_name: 'Bitter Aperitif' }],
          ])}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText(/PARENTS · 2/)).toBeInTheDocument();
    expect(screen.getByText(/Amari/)).toBeInTheDocument();
    expect(screen.getByText('#17')).toBeInTheDocument();
  });

  it('clicking pencil on PARENTS section calls onEditParents', async () => {
    const onEditParents = vi.fn();
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <NodeCard
          node={makeNode()}
          mode="pinned"
          onDismiss={vi.fn()}
          onEditField={vi.fn()}
          onEditParents={onEditParents}
          onDelete={vi.fn()}
          parentLookup={new Map([[17, { id: 17, display_name: 'Amari' }], [84, { id: 84, display_name: 'Bitter Aperitif' }]])}
        />
      </MemoryRouter>,
    );
    await user.hover(screen.getByText(/PARENTS · 2/));
    await user.click(screen.getByRole('button', { name: /edit parents/i }));
    expect(onEditParents).toHaveBeenCalledWith(42);
  });

  it('hover mode hides Delete link and edit affordances', () => {
    render(
      <MemoryRouter>
        <NodeCard
          node={makeNode()}
          mode="hover"
          onDismiss={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument();
  });

  it('clicking Delete in pinned mode calls onDelete with node id', async () => {
    const onDelete = vi.fn();
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <NodeCard
          node={makeNode()}
          mode="pinned"
          onDismiss={vi.fn()}
          onEditField={vi.fn()}
          onEditParents={vi.fn()}
          onDelete={onDelete}
        />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole('button', { name: /delete node/i }));
    expect(onDelete).toHaveBeenCalledWith(42);
  });
});
