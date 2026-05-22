import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ProposalDetail } from './ProposalDetail';

const proposal = {
  id: 7,
  raw_string: 'lemon zest',
  proposed_slug: 'lemon-zest',
  proposed_display_name: 'Lemon Zest',
  proposed_parent_id: 99,
  proposed_parent_display_name: 'Citrus',
  candidates: [
    { node_id: 10, display_name: 'Lemon Peel', similarity: 0.87 },
  ],
  mapper_version: 'v-test',
  created_at: '2026-05-21T10:00:00Z',
};

const NODES = [
  { id: 10, slug: 'lemon-peel', display_name: 'Lemon Peel', aliases: [] },
  { id: 99, slug: 'citrus', display_name: 'Citrus', aliases: [] },
];

function setup(over: Partial<Parameters<typeof ProposalDetail>[0]> = {}) {
  const handlers = {
    onCreate: vi.fn().mockResolvedValue(undefined),
    onMapToExisting: vi.fn().mockResolvedValue(undefined),
    onFlag: vi.fn().mockResolvedValue(undefined),
    onDefer: vi.fn(),
  };
  render(
    <ProposalDetail
      proposal={proposal}
      nodes={NODES}
      flagReasons={[]}
      {...handlers}
      {...over}
    />,
  );
  return handlers;
}

describe('<ProposalDetail>', () => {
  it('renders raw_string, proposed slug + parent prominently', () => {
    setup();
    expect(screen.getByText('lemon zest')).toBeInTheDocument();
    expect(screen.getByDisplayValue('lemon-zest')).toBeInTheDocument();
    expect(screen.getByText(/Citrus/)).toBeInTheDocument();
  });

  it('Create calls onCreate with the (possibly edited) slug', async () => {
    const h = setup();
    const user = userEvent.setup();
    const slugInput = screen.getByDisplayValue('lemon-zest');
    await user.clear(slugInput);
    await user.type(slugInput, 'citrus-zest-lemon');
    await user.click(screen.getByRole('button', { name: /^create$/i }));
    await waitFor(() => expect(h.onCreate).toHaveBeenCalledWith(7, 'citrus-zest-lemon'));
  });

  it('Create blocks with invalid slug (underscore)', async () => {
    const h = setup();
    const user = userEvent.setup();
    const slugInput = screen.getByDisplayValue('lemon-zest');
    await user.clear(slugInput);
    await user.type(slugInput, 'lemon_zest');
    await user.click(screen.getByRole('button', { name: /^create$/i }));
    expect(h.onCreate).not.toHaveBeenCalled();
    expect(screen.getByText(/kebab-case/i)).toBeInTheDocument();
  });

  it('clicking a candidate pre-targets Map-to-existing with that node', async () => {
    const h = setup();
    const user = userEvent.setup();
    await user.click(screen.getByText(/Lemon Peel/));
    await user.click(screen.getByRole('button', { name: /confirm map/i }));
    await waitFor(() => expect(h.onMapToExisting).toHaveBeenCalledWith(7, 10));
  });

  it('Flag opens FlagInput; saving calls onFlag', async () => {
    const h = setup();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /^flag$/i }));
    await user.type(screen.getByLabelText(/flag reason/i), 'needs research');
    await user.click(screen.getByRole('button', { name: /save flag/i }));
    await waitFor(() => expect(h.onFlag).toHaveBeenCalledWith(7, 'needs research'));
  });

  it('Defer calls onDefer immediately', async () => {
    const h = setup();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /defer/i }));
    expect(h.onDefer).toHaveBeenCalledWith(7);
  });
});
