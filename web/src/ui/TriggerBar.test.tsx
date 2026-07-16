import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TriggerBar } from './TriggerBar';

const rpcMock = vi.fn();
const fromMock = vi.fn();

vi.mock('../supabase', () => ({
  supabase: {
    rpc: (...args: unknown[]) => rpcMock(...args),
    from: (table: string) => fromMock(table),
    channel: vi.fn(() => {
      const chan = { on: () => chan, subscribe: (cb: (s: string) => void) => { cb('SUBSCRIBED'); return chan; } };
      return chan;
    }),
    removeChannel: vi.fn(),
  },
}));

function mockStageConfig(rows: { stage: string; metered: boolean; requires_approval: boolean }[]) {
  fromMock.mockImplementation((table: string) => {
    if (table === 'stage_config') {
      return { select: vi.fn().mockResolvedValue({ data: rows, error: null }) };
    }
    if (table === 'jobs') {
      return { select: vi.fn(() => ({ eq: vi.fn().mockResolvedValue({ data: [], error: null }) })) };
    }
    throw new Error(`unexpected table ${table}`);
  });
}

function wrapperWith(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

beforeEach(() => {
  rpcMock.mockReset();
  fromMock.mockReset();
});

describe('<TriggerBar> scope building', () => {
  it('item scope: entityId prop -> enqueues {kind:"item", stage, entity_id}', async () => {
    mockStageConfig([{ stage: 'extract', metered: false, requires_approval: false }]);
    rpcMock.mockResolvedValue({ data: 1, error: null });
    const user = userEvent.setup();
    render(<TriggerBar stage="extract" entityId="42" />, { wrapper: wrapperWith(makeClient()) });

    await user.click(screen.getByRole('button', { name: /run/i }));
    await waitFor(() => expect(rpcMock).toHaveBeenCalledWith('enqueue_job', expect.objectContaining({
      p_payload: { scope: { kind: 'item', stage: 'extract', entity_id: '42' } },
    })));
  });

  it('multiselect scope: selectedIds prop -> enqueues {kind:"multiselect", entity_ids}', async () => {
    mockStageConfig([{ stage: 'extract', metered: false, requires_approval: false }]);
    rpcMock.mockResolvedValue({ data: 1, error: null });
    const user = userEvent.setup();
    render(<TriggerBar stage="extract" selectedIds={[1, 2, 3]} />, { wrapper: wrapperWith(makeClient()) });

    await user.click(screen.getByRole('button', { name: /run/i }));
    await waitFor(() => expect(rpcMock).toHaveBeenCalledWith('enqueue_job', expect.objectContaining({
      p_payload: { scope: { kind: 'multiselect', stage: 'extract', entity_ids: ['1', '2', '3'] } },
    })));
  });

  it('whole_queue scope: no entityId/selectedIds/filterScope -> enqueues {kind:"whole_queue"}', async () => {
    mockStageConfig([{ stage: 'extract', metered: false, requires_approval: false }]);
    rpcMock.mockResolvedValue({ data: 1, error: null });
    const user = userEvent.setup();
    render(<TriggerBar stage="extract" />, { wrapper: wrapperWith(makeClient()) });

    await user.click(screen.getByRole('button', { name: /run/i }));
    await waitFor(() => expect(rpcMock).toHaveBeenCalledWith('enqueue_job', expect.objectContaining({
      p_payload: { scope: { kind: 'whole_queue', stage: 'extract' } },
    })));
  });

  it('filter scope: the exact FilterBar-emitted object is forwarded, not rebuilt', async () => {
    mockStageConfig([{ stage: 'extract', metered: false, requires_approval: false }]);
    rpcMock.mockResolvedValue({ data: 1, error: null });
    const user = userEvent.setup();
    const filterScope = { kind: 'filter' as const, stage: 'extract', site: 'punch', where: [{ col: 'site', op: 'eq' as const, value: 'punch' }] };
    render(<TriggerBar stage="extract" filterScope={filterScope} />, { wrapper: wrapperWith(makeClient()) });

    await user.click(screen.getByRole('button', { name: /run/i }));
    await waitFor(() => expect(rpcMock).toHaveBeenCalled());
    const call = rpcMock.mock.calls.find((c) => c[0] === 'enqueue_job')!;
    expect((call[1] as { p_payload: { scope: unknown } }).p_payload.scope).toBe(filterScope);
  });
});

describe('<TriggerBar> metered gate', () => {
  it('free stage: clicking run enqueues immediately, no CostConfirmModal', async () => {
    mockStageConfig([{ stage: 'parse', metered: false, requires_approval: false }]);
    rpcMock.mockResolvedValue({ data: 1, error: null });
    const user = userEvent.setup();
    render(<TriggerBar stage="parse" />, { wrapper: wrapperWith(makeClient()) });

    await user.click(screen.getByRole('button', { name: /run/i }));
    await waitFor(() => expect(rpcMock).toHaveBeenCalledWith('enqueue_job', expect.anything()));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('metered stage: clicking run opens CostConfirmModal instead of enqueuing', async () => {
    mockStageConfig([{ stage: 'fetch', metered: true, requires_approval: true }]);
    const user = userEvent.setup();
    render(<TriggerBar stage="fetch" />, { wrapper: wrapperWith(makeClient()) });

    await waitFor(() => expect(fromMock).toHaveBeenCalledWith('stage_config'));
    await user.click(screen.getByRole('button', { name: /run/i }));

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(rpcMock).not.toHaveBeenCalledWith('enqueue_job', expect.anything());
  });

  it('metered stage: confirming the modal enqueues, approves, and tracks progress via a persistent toast', async () => {
    mockStageConfig([{ stage: 'fetch', metered: true, requires_approval: true }]);
    rpcMock.mockImplementation((fn: string) => {
      if (fn === 'enqueue_job') return Promise.resolve({ data: 99, error: null });
      if (fn === 'approve_job') return Promise.resolve({ data: null, error: null });
      throw new Error(`unexpected rpc ${fn}`);
    });
    const user = userEvent.setup();
    render(<TriggerBar stage="fetch" />, { wrapper: wrapperWith(makeClient()) });

    await waitFor(() => expect(fromMock).toHaveBeenCalledWith('stage_config'));
    await user.click(screen.getByRole('button', { name: /run/i }));
    await screen.findByRole('dialog');

    await user.click(screen.getByRole('checkbox', { name: /acknowledge/i }));
    await user.type(screen.getByLabelText(/max cost/i), '1000');
    await user.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(await screen.findByRole('status')).toHaveTextContent(/99/);
  });
});
