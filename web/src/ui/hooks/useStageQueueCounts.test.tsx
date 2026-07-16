import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const rpcMock = vi.fn();
vi.mock('../../supabase', () => ({ supabase: { rpc: (...args: unknown[]) => rpcMock(...args) } }));

import { useStageQueueCounts, queueDepthForStage } from './useStageQueueCounts';

function wrapperWith(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

beforeEach(() => {
  rpcMock.mockReset();
});

describe('useStageQueueCounts', () => {
  it('calls the stage_queue_counts RPC once and returns its rows', async () => {
    rpcMock.mockResolvedValue({
      data: [{ stage: 'parse', queue_depth: 4 }, { stage: 'export', queue_depth: 0 }],
      error: null,
    });

    const { result } = renderHook(() => useStageQueueCounts(), { wrapper: wrapperWith(makeClient()) });

    await waitFor(() => expect(result.current.status).toBe('loaded'));
    expect(rpcMock).toHaveBeenCalledWith('stage_queue_counts');
    expect(result.current.rows).toEqual([
      { stage: 'parse', queue_depth: 4 },
      { stage: 'export', queue_depth: 0 },
    ]);
  });

  it('surfaces an error status when the RPC fails', async () => {
    rpcMock.mockResolvedValue({ data: null, error: { message: 'nope' } });
    const { result } = renderHook(() => useStageQueueCounts(), { wrapper: wrapperWith(makeClient()) });
    await waitFor(() => expect(result.current.status).toBe('error'));
  });
});

describe('queueDepthForStage', () => {
  const rows = [{ stage: 'parse', queue_depth: 4 }, { stage: 'export', queue_depth: 0 }];

  it('returns the depth for a tracked stage, including an explicit zero', () => {
    expect(queueDepthForStage(rows, 'parse')).toBe(4);
    expect(queueDepthForStage(rows, 'export')).toBe(0);
  });

  it('returns null for a stage with no row (untracked)', () => {
    expect(queueDepthForStage(rows, 'discover')).toBeNull();
  });
});
