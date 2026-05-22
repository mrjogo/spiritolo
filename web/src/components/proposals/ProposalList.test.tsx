import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ProposalList } from './ProposalList';

const PROPOSALS = [
  {
    id: 1, raw_string: 'lemon zest', proposed_slug: 'lemon-zest',
    proposed_display_name: 'Lemon Zest', proposed_parent_id: 99,
    proposed_parent_display_name: 'Citrus', candidates: [],
    mapper_version: 'v-test', created_at: '2026-05-21T00:00:00Z',
  },
  {
    id: 2, raw_string: 'rye whiskey', proposed_slug: 'rye-whiskey',
    proposed_display_name: 'Rye Whiskey', proposed_parent_id: 50,
    proposed_parent_display_name: 'Whiskey', candidates: [],
    mapper_version: 'v-test', created_at: '2026-05-21T00:00:01Z',
  },
];

const PARENTS = [
  { proposed_parent_id: 99, proposed_parent_display_name: 'Citrus', pending_count: 1 },
  { proposed_parent_id: 50, proposed_parent_display_name: 'Whiskey', pending_count: 1 },
];

describe('<ProposalList>', () => {
  it('renders one row per proposal with raw_string → slug', () => {
    render(
      <ProposalList
        proposals={PROPOSALS} parents={PARENTS}
        selectedId={null} onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText(/lemon zest → lemon-zest/)).toBeInTheDocument();
    expect(screen.getByText(/rye whiskey → rye-whiskey/)).toBeInTheDocument();
  });

  it('shows total pending count', () => {
    render(
      <ProposalList
        proposals={PROPOSALS} parents={PARENTS}
        selectedId={null} onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText(/2 pending/i)).toBeInTheDocument();
  });

  it('filters by proposed_parent_id when a bucket is chosen', async () => {
    const user = userEvent.setup();
    render(
      <ProposalList
        proposals={PROPOSALS} parents={PARENTS}
        selectedId={null} onSelect={vi.fn()}
      />,
    );
    await user.selectOptions(
      screen.getByLabelText(/filter by parent/i),
      'Whiskey',
    );
    expect(screen.queryByText(/lemon zest/)).not.toBeInTheDocument();
    expect(screen.getByText(/rye whiskey/)).toBeInTheDocument();
  });

  it('clicking a row calls onSelect with the proposal id', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(
      <ProposalList
        proposals={PROPOSALS} parents={PARENTS}
        selectedId={null} onSelect={onSelect}
      />,
    );
    await user.click(screen.getByText(/rye whiskey/));
    expect(onSelect).toHaveBeenCalledWith(2);
  });
});
