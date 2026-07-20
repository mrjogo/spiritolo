import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

type ChangeHandler = (payload: unknown) => void;
type StatusHandler = (status: string) => void;

const fromSelectMock = vi.fn();
let capturedOnChange: ChangeHandler | null = null;
let capturedSubscribe: StatusHandler | null = null;
const removeChannelMock = vi.fn();

function makeChain(table: string) {
  const chain = {
    eq: vi.fn(() => chain),
    // supabase-js query builders are themselves thenable — `await q` calls
    // this directly without a terminal method. Mirror that so the hook can
    // chain zero, one, or two .eq() calls before awaiting.
    then: (onFulfilled: (v: unknown) => unknown, onRejected?: (e: unknown) => unknown) =>
      Promise.resolve(fromSelectMock(table)).then(onFulfilled, onRejected),
  };
  return chain;
}

vi.mock('../../supabase', () => ({
  supabase: {
    from: (table: string) => ({
      select: () => makeChain(table),
    }),
    channel: vi.fn(() => {
      const chan = {
        on: (_type: string, _filter: unknown, handler: ChangeHandler) => {
          capturedOnChange = handler;
          return chan;
        },
        subscribe: (cb: StatusHandler) => {
          capturedSubscribe = cb;
          return chan;
        },
      };
      return chan;
    }),
    removeChannel: (...args: unknown[]) => removeChannelMock(...args),
  },
}));

import { useRealtimeJobs } from './useRealtimeJobs';

function wrapperWith(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

beforeEach(() => {
  vi.clearAllMocks();
  capturedOnChange = null;
  capturedSubscribe = null;
  fromSelectMock.mockResolvedValue({ data: [{ id: 1, stage: 'extract-recipe', state: 'queued' }], error: null });
});

describe('useRealtimeJobs', () => {
  it('merges a postgres_changes payload into the cache without a refetch', async () => {
    const { result } = renderHook(() => useRealtimeJobs({ stage: 'extract-recipe' }), {
      wrapper: wrapperWith(makeClient()),
    });

    await waitFor(() => expect(result.current.jobs).toHaveLength(1));
    expect(fromSelectMock).toHaveBeenCalledTimes(1);

    capturedSubscribe?.('SUBSCRIBED');
    await waitFor(() => expect(result.current.connected).toBe(true));

    capturedOnChange?.({
      eventType: 'UPDATE',
      new: { id: 1, stage: 'extract-recipe', state: 'running' },
      old: { id: 1, stage: 'extract-recipe', state: 'queued' },
    });

    await waitFor(() =>
      expect(result.current.jobs).toEqual([{ id: 1, stage: 'extract-recipe', state: 'running' }]),
    );
    // No additional fetch was triggered — the realtime payload updated the
    // cache directly.
    expect(fromSelectMock).toHaveBeenCalledTimes(1);
  });

  it('falls back to polling and reports connected=false when the channel never subscribes', async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useRealtimeJobs({ stage: 'extract-recipe' }), {
      wrapper: wrapperWith(makeClient()),
    });

    await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));
    expect(result.current.connected).toBe(false);

    fromSelectMock.mockResolvedValue({
      data: [{ id: 1, stage: 'extract-recipe', state: 'succeeded' }],
      error: null,
    });

    await vi.advanceTimersByTimeAsync(3500);
    await vi.waitFor(() => expect(fromSelectMock.mock.calls.length).toBeGreaterThan(1));

    vi.useRealTimers();
  });
});
