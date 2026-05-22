import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Mutable backing store so RPC mocks can shrink the list.
const state = {
  proposals: [
    { id: 1, raw_string: 'lemon zest', proposed_slug: 'lemon-zest',
      proposed_display_name: 'Lemon Zest', proposed_parent_id: 99,
      proposed_parent_display_name: 'Citrus',
      candidates: [{ node_id: 10, display_name: 'Lemon Peel', similarity: 0.9 }],
      mapper_version: 'v-test', created_at: '2026-05-21T00:00:00Z' },
    { id: 2, raw_string: 'lime juice', proposed_slug: 'lime-juice',
      proposed_display_name: 'Lime Juice', proposed_parent_id: 99,
      proposed_parent_display_name: 'Citrus',
      candidates: [],
      mapper_version: 'v-test', created_at: '2026-05-21T00:00:01Z' },
    { id: 3, raw_string: 'mystery thing', proposed_slug: 'mystery-thing',
      proposed_display_name: 'Mystery Thing', proposed_parent_id: 50,
      proposed_parent_display_name: 'Whiskey',
      candidates: [],
      mapper_version: 'v-test', created_at: '2026-05-21T00:00:02Z' },
  ] as Array<Record<string, unknown>>,
};

const rpcs = vi.hoisted(() => ({
  applyProposalCreate: vi.fn(async (id: number) => {
    state.proposals = state.proposals.filter((p) => p.id !== id);
    return 999;
  }),
  applyProposalMapToExisting: vi.fn(async (id: number) => {
    state.proposals = state.proposals.filter((p) => p.id !== id);
  }),
  applyProposalFlag: vi.fn(async (id: number) => {
    state.proposals = state.proposals.filter((p) => p.id !== id);
  }),
}));
vi.mock('../components/proposals/rpcs', () => rpcs);

vi.mock('../supabase', () => ({
  supabase: {
    from: (t: string) => {
      if (t === 'pending_proposals_view') {
        return { select: () => ({ order: () => Promise.resolve({ data: state.proposals, error: null }) }) };
      }
      if (t === 'pending_proposals_parents_view') {
        return { select: () => ({ order: () => Promise.resolve({
          data: [
            { proposed_parent_id: 99, proposed_parent_display_name: 'Citrus', pending_count: 2 },
            { proposed_parent_id: 50, proposed_parent_display_name: 'Whiskey', pending_count: 1 },
          ], error: null }) }) };
      }
      if (t === 'recipe_ingredients') {
        return { select: () => ({ not: () => Promise.resolve({ data: [], error: null }) }) };
      }
      if (t === 'taxonomy_public') {
        return { select: () => Promise.resolve({
          data: [{ id: 10, slug: 'lemon-peel', display_name: 'Lemon Peel', aliases: [] }],
          error: null }) };
      }
      throw new Error(`unexpected table: ${t}`);
    },
  },
}));

import { Proposals } from './Proposals';

beforeEach(() => {
  state.proposals = [
    { id: 1, raw_string: 'lemon zest', proposed_slug: 'lemon-zest',
      proposed_display_name: 'Lemon Zest', proposed_parent_id: 99,
      proposed_parent_display_name: 'Citrus',
      candidates: [{ node_id: 10, display_name: 'Lemon Peel', similarity: 0.9 }],
      mapper_version: 'v-test', created_at: '2026-05-21T00:00:00Z' },
    { id: 2, raw_string: 'lime juice', proposed_slug: 'lime-juice',
      proposed_display_name: 'Lime Juice', proposed_parent_id: 99,
      proposed_parent_display_name: 'Citrus',
      candidates: [],
      mapper_version: 'v-test', created_at: '2026-05-21T00:00:01Z' },
    { id: 3, raw_string: 'mystery thing', proposed_slug: 'mystery-thing',
      proposed_display_name: 'Mystery Thing', proposed_parent_id: 50,
      proposed_parent_display_name: 'Whiskey',
      candidates: [],
      mapper_version: 'v-test', created_at: '2026-05-21T00:00:02Z' },
  ];
  rpcs.applyProposalCreate.mockClear();
  rpcs.applyProposalMapToExisting.mockClear();
  rpcs.applyProposalFlag.mockClear();
});

function renderApp() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Proposals /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Proposals page — end-to-end happy path', () => {
  it('drains the list through Create then Map then Flag', async () => {
    const user = userEvent.setup();
    renderApp();

    // Initial load: 3 pending.
    await screen.findByText(/3 pending/i);

    // CREATE on the first row (auto-selected).
    await user.click(await screen.findByRole('button', { name: /^create$/i }));
    await waitFor(() => expect(rpcs.applyProposalCreate).toHaveBeenCalledTimes(1));
    await screen.findByText(/2 pending/i);

    // MAP via candidates: click "Lemon Peel"-equivalent candidate — but the
    // remaining selected proposal (lime juice) has no candidates, so use
    // Map-to-existing then NodePicker. Use direct picker route.
    await user.click(await screen.findByRole('button', { name: /map to existing/i }));
    await user.click(await screen.findByText(/Lemon Peel · lemon-peel/));
    await user.click(await screen.findByRole('button', { name: /confirm map/i }));
    await waitFor(() => expect(rpcs.applyProposalMapToExisting).toHaveBeenCalledTimes(1));
    await screen.findByText(/1 pending/i);

    // FLAG on the last row.
    await user.click(await screen.findByRole('button', { name: /^flag$/i }));
    await user.type(await screen.findByLabelText(/flag reason/i), 'needs research');
    await user.click(await screen.findByRole('button', { name: /save flag/i }));
    await waitFor(() => expect(rpcs.applyProposalFlag).toHaveBeenCalledTimes(1));
    await screen.findByText(/no pending proposals/i);
  });
});
