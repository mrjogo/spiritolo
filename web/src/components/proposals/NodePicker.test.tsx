import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NodePicker } from './NodePicker';

const NODES = [
  { id: 1, slug: 'lemon-peel', display_name: 'Lemon Peel', aliases: [] },
  { id: 2, slug: 'lime-zest', display_name: 'Lime Zest', aliases: ['lime peel'] },
  { id: 3, slug: 'orange-bitters', display_name: 'Orange Bitters', aliases: [] },
];

describe('<NodePicker>', () => {
  it('shows all nodes alphabetically when query is empty', () => {
    render(
      <NodePicker nodes={NODES} value={null} onChange={vi.fn()} />,
    );
    const opts = screen.getAllByRole('option').map((o) => o.textContent);
    expect(opts.slice(0, 3)).toEqual([
      'Lemon Peel · lemon-peel',
      'Lime Zest · lime-zest',
      'Orange Bitters · orange-bitters',
    ]);
  });

  it('filters by substring across display_name / slug / aliases', async () => {
    const user = userEvent.setup();
    render(<NodePicker nodes={NODES} value={null} onChange={vi.fn()} />);
    await user.type(screen.getByLabelText(/search nodes/i), 'lime peel');
    const opts = screen.getAllByRole('option').map((o) => o.textContent);
    expect(opts).toEqual(['Lime Zest · lime-zest']);
  });

  it('calls onChange with id when user clicks a result', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<NodePicker nodes={NODES} value={null} onChange={onChange} />);
    await user.click(screen.getByText('Orange Bitters · orange-bitters'));
    expect(onChange).toHaveBeenCalledWith(3);
  });

  it('Enter selects the highlighted result', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<NodePicker nodes={NODES} value={null} onChange={onChange} />);
    const input = screen.getByLabelText(/search nodes/i);
    await user.type(input, 'lim');
    await user.keyboard('{Enter}');
    expect(onChange).toHaveBeenCalledWith(2);
  });
});
