import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CostConfirmModal } from './CostConfirmModal';

const rpcMock = vi.fn();
vi.mock('../supabase', () => ({ supabase: { rpc: (...args: unknown[]) => rpcMock(...args) } }));

function wrapperWith(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

function renderModal(props: Partial<Parameters<typeof CostConfirmModal>[0]> = {}) {
  const client = makeClient();
  const onCancel = vi.fn();
  const onConfirmed = vi.fn();
  const utils = render(
    <CostConfirmModal
      stage="fetch"
      scope={{ kind: 'whole_queue', stage: 'fetch' }}
      itemCount={40}
      onCancel={onCancel}
      onConfirmed={onConfirmed}
      {...props}
    />,
    { wrapper: wrapperWith(client) },
  );
  return { ...utils, onCancel, onConfirmed };
}

beforeEach(() => {
  rpcMock.mockReset();
});

describe('<CostConfirmModal>', () => {
  it('shows item count and a CostBadge estimate, and disables Confirm until acknowledged + a max cost is entered', async () => {
    const user = userEvent.setup();
    renderModal({ itemCount: 40, estimatedCentsPerItem: 2 });

    expect(screen.getByText(/40/)).toBeInTheDocument();
    // 40 items * 2c = 80c = $0.80 estimate.
    expect(screen.getByText('$0.80')).toBeInTheDocument();

    const confirm = screen.getByRole('button', { name: /^confirm$/i });
    expect(confirm).toBeDisabled();

    await user.click(screen.getByRole('checkbox', { name: /acknowledge/i }));
    expect(confirm).toBeDisabled(); // still no max cost entered

    await user.type(screen.getByLabelText(/max cost/i), '500');
    expect(confirm).not.toBeDisabled();
  });

  it('shows a placeholder (not a fabricated number) when item count is unknown', () => {
    renderModal({ itemCount: undefined });
    // Both the item-count row and the CostBadge estimate fall back to an
    // em-dash rather than a guessed number.
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2);
  });

  it('on confirm, calls enqueue_job then approve_job with the returned id, then onConfirmed', async () => {
    const user = userEvent.setup();
    rpcMock.mockImplementation((fn: string) => {
      if (fn === 'enqueue_job') return Promise.resolve({ data: 77, error: null });
      if (fn === 'approve_job') return Promise.resolve({ data: null, error: null });
      throw new Error(`unexpected rpc ${fn}`);
    });

    const { onConfirmed } = renderModal({
      stage: 'fetch',
      version: 'v3',
      scope: { kind: 'whole_queue', stage: 'fetch' },
      itemCount: 10,
      estimatedCentsPerItem: 5,
    });

    await user.click(screen.getByRole('checkbox', { name: /acknowledge/i }));
    await user.type(screen.getByLabelText(/max cost/i), '1000');
    await user.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => expect(onConfirmed).toHaveBeenCalledWith(77));

    expect(rpcMock).toHaveBeenCalledWith('enqueue_job', {
      p_stage: 'fetch',
      p_kind: 'run',
      p_payload: { scope: { kind: 'whole_queue', stage: 'fetch' } },
      p_version: 'v3',
      p_requires_approval: true,
      p_cost_estimate_cents: 50,
      p_max_cost_cents: 1000,
    });
    expect(rpcMock).toHaveBeenCalledWith('approve_job', { p_id: 77 });

    // enqueue must be called before approve.
    const enqueueCallIdx = rpcMock.mock.calls.findIndex((c) => c[0] === 'enqueue_job');
    const approveCallIdx = rpcMock.mock.calls.findIndex((c) => c[0] === 'approve_job');
    expect(enqueueCallIdx).toBeLessThan(approveCallIdx);
  });

  it('clicking Cancel calls onCancel without enqueueing anything', async () => {
    const user = userEvent.setup();
    const { onCancel } = renderModal();
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalled();
    expect(rpcMock).not.toHaveBeenCalled();
  });
});
