import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
