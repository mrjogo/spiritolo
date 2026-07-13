import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// StageCard composes TriggerBar for the whole-queue affordance; assert the
// composition by role/label rather than re-testing TriggerBar's own
// scope/metering behavior (that lives in TriggerBar.test.tsx).
vi.mock('../../ui/TriggerBar', () => ({
  TriggerBar: ({ stage }: { stage: string }) => (
    <div role="region" aria-label={`trigger for ${stage}`} />
  ),
}));

const fromMock = vi.fn();
const rpcMock = vi.fn();
vi.mock('../../supabase', () => ({
  supabase: {
    from: (table: string) => fromMock(table),
    rpc: (fn: string) => rpcMock(fn),
    channel: vi.fn(() => {
      const chan = { on: () => chan, subscribe: (cb: (s: string) => void) => { cb('SUBSCRIBED'); return chan; } };
      return chan;
    }),
    removeChannel: vi.fn(),
  },
}));

import { StageCard } from './StageCard';

interface OutcomeRow { outcome: string; run_count: number; cost_cents: number | null }
interface JobRow { id: number; stage: string; state: string }
interface QueueRow { stage: string; queue_depth: number }

function mockTables(outcomeRows: OutcomeRow[], jobRows: JobRow[], queueRows: QueueRow[] = []) {
  fromMock.mockImplementation((table: string) => {
    if (table === 'stage_run_outcome_counts') {
      const range = vi.fn().mockResolvedValue({ data: outcomeRows, count: outcomeRows.length, error: null });
      const eq = vi.fn(() => ({ range }));
      return { select: vi.fn(() => ({ eq })) };
    }
    if (table === 'jobs') {
      const eq = vi.fn().mockResolvedValue({ data: jobRows, error: null });
      return { select: vi.fn(() => ({ eq })) };
    }
    throw new Error(`unexpected table ${table}`);
  });
  rpcMock.mockImplementation((fn: string) => {
    if (fn === 'stage_queue_counts') {
      return Promise.resolve({ data: queueRows, error: null });
    }
    throw new Error(`unexpected rpc ${fn}`);
  });
}

function wrapperWith(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

beforeEach(() => {
  fromMock.mockReset();
  rpcMock.mockReset();
});

describe('<StageCard>', () => {
  it('renders the outcome mix as a StatusPill row with counts, and the accumulated cost', async () => {
    mockTables(
      [
        { outcome: 'resolved', run_count: 12, cost_cents: 340 },
        { outcome: 'abstain', run_count: 3, cost_cents: 0 },
      ],
      [],
    );
    render(<StageCard stage="extract" />, { wrapper: wrapperWith(makeClient()) });

    expect(await screen.findByText('resolved')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('abstain')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    // Accumulated cost = sum(cost_cents) across outcomes = 340c = $3.40.
    expect(screen.getByText('$3.40')).toBeInTheDocument();
  });

  it('shows in-flight count from live jobs (running/claimed), not from the outcome view', async () => {
    mockTables(
      [{ outcome: 'resolved', run_count: 1, cost_cents: 0 }],
      [
        { id: 1, stage: 'fetch', state: 'running' },
        { id: 2, stage: 'fetch', state: 'claimed' },
        { id: 3, stage: 'fetch', state: 'succeeded' },
      ],
    );
    render(<StageCard stage="fetch" />, { wrapper: wrapperWith(makeClient()) });

    await waitFor(() => expect(screen.getByLabelText(/in-flight/i)).toHaveTextContent('2'));
  });

  it('renders the real queue depth from stage_queue_counts for a tracked stage', async () => {
    mockTables([], [], [{ stage: 'map', queue_depth: 7 }]);
    render(<StageCard stage="map" />, { wrapper: wrapperWith(makeClient()) });
    expect(await screen.findByText(/queue depth/i)).toBeInTheDocument();
    expect(await screen.findByText('7')).toBeInTheDocument();
  });

  it('renders an explicit zero, not a placeholder, when a tracked stage has caught up', async () => {
    mockTables([], [], [{ stage: 'export', queue_depth: 0 }]);
    render(<StageCard stage="export" />, { wrapper: wrapperWith(makeClient()) });
    expect(await screen.findByText(/queue depth/i)).toBeInTheDocument();
    expect(await screen.findByText('0')).toBeInTheDocument();
  });

  it('marks the content-queue-depth as not-tracked rather than fabricating a number for a stage with no row', async () => {
    mockTables([], [], [{ stage: 'map', queue_depth: 7 }]);
    render(<StageCard stage="discover" />, { wrapper: wrapperWith(makeClient()) });
    expect(await screen.findByText(/queue depth/i)).toBeInTheDocument();
    expect(await screen.findByText(/not tracked/i)).toBeInTheDocument();
  });

  it('composes the shared TriggerBar for the whole-queue affordance', async () => {
    mockTables([], []);
    render(<StageCard stage="cluster" />, { wrapper: wrapperWith(makeClient()) });
    expect(await screen.findByRole('region', { name: 'trigger for cluster' })).toBeInTheDocument();
  });

  it('shows a neutral message when a stage has no runs yet', async () => {
    mockTables([], []);
    render(<StageCard stage="role" />, { wrapper: wrapperWith(makeClient()) });
    expect(await screen.findByText(/no runs yet/i)).toBeInTheDocument();
  });
});
