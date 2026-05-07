import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../../supabase', () => ({
  supabase: {
    from: vi.fn().mockReturnValue({
      select: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          order: vi.fn().mockReturnValue({
            then: vi.fn().mockImplementation((cb: (result: { data: unknown[]; error: null }) => void) => {
              cb({ data: [], error: null });
            }),
          }),
        }),
      }),
    }),
  },
}));

import { supabase } from '../../supabase';
import { NodeCard } from './NodeCard';
import type { TaxonomyNode } from './shapeData';

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
    render(<NodeCard node={node} mode="pinned" onDismiss={() => {}} />);
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
    const { rerender } = render(<NodeCard node={node} mode="pinned" onDismiss={onDismiss} />);
    const close = screen.getByRole('button', { name: /close/i });
    await user.click(close);
    expect(onDismiss).toHaveBeenCalled();

    rerender(<NodeCard node={node} mode="hover" onDismiss={onDismiss} />);
    expect(screen.queryByRole('button', { name: /close/i })).toBeNull();
  });

  it('calls onDismiss when Escape is pressed in pinned mode', async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    render(<NodeCard node={node} mode="pinned" onDismiss={onDismiss} />);
    await user.keyboard('{Escape}');
    expect(onDismiss).toHaveBeenCalled();
  });

  it('does NOT call onDismiss on Escape in hover mode', async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    render(<NodeCard node={node} mode="hover" onDismiss={onDismiss} />);
    await user.keyboard('{Escape}');
    expect(onDismiss).not.toHaveBeenCalled();
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
