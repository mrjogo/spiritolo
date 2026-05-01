import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SpecimenCard } from './SpecimenCard';
import type { TaxonomyNode } from './shapeData';

const node: TaxonomyNode = {
  id: 1, slug: 'rye_whiskey', display_name: 'Rye Whiskey',
  role: null, role_default: 'substance',
  is_cluster_node: true, is_defining_garnish: false,
  parent_ids: [10, 11], child_ids: [20, 21],
  aliases: ['rye', 'rye whisky'], recipe_count: 47,
};

describe('<SpecimenCard>', () => {
  it('renders the focused node properties', () => {
    render(<SpecimenCard node={node} onDismiss={() => {}} />);
    expect(screen.getByText('RYE WHISKEY')).toBeInTheDocument();
    expect(screen.getByText(/47 drinks call for this/i)).toBeInTheDocument();
    expect(screen.getByText(/rye, rye whisky/)).toBeInTheDocument();
    expect(screen.getByText(/cluster node/i)).toBeInTheDocument();
  });

  it('calls onDismiss when Escape is pressed', async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    render(<SpecimenCard node={node} onDismiss={onDismiss} />);
    await user.keyboard('{Escape}');
    expect(onDismiss).toHaveBeenCalled();
  });

  it('writes the slug to the clipboard when the slug row is clicked', async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });
    render(<SpecimenCard node={node} onDismiss={() => {}} />);
    await user.click(screen.getByText(/rye_whiskey/));
    expect(writeText).toHaveBeenCalledWith('rye_whiskey');
  });
});
