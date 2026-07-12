import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const rpcMock = vi.fn();
vi.mock('../../supabase', () => ({ supabase: { rpc: (...args: unknown[]) => rpcMock(...args) } }));

import { useRpc } from './useRpc';
import { RpcError } from '../../components/taxonomy/rpcs';

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
});

describe('useRpc', () => {
  it('unwraps a successful rpc call and calls supabase.rpc with the args', async () => {
    rpcMock.mockResolvedValue({ data: { ok: true }, error: null });
    const { result } = renderHook(() => useRpc<{ p_id: number }, { ok: boolean }>('do_thing'), {
      wrapper: wrapperWith(makeClient()),
    });

    result.current.mutate({ p_id: 1 });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ ok: true });
    expect(rpcMock).toHaveBeenCalledWith('do_thing', { p_id: 1 });
  });

  it('rejects with RpcError (carrying the original error as cause) on an rpc error', async () => {
    rpcMock.mockResolvedValue({ data: null, error: { message: 'nope', code: '42501' } });
    const { result } = renderHook(() => useRpc('do_thing'), {
      wrapper: wrapperWith(makeClient()),
    });

    result.current.mutate({});

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(RpcError);
    expect((result.current.error as RpcError).cause).toMatchObject({ code: '42501' });
  });

  it('invalidates the given query keys only on success', async () => {
    const client = makeClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
    rpcMock.mockResolvedValue({ data: { ok: true }, error: null });
    const { result } = renderHook(
      () => useRpc('do_thing', { invalidate: [['jobs']] }),
      { wrapper: wrapperWith(client) },
    );

    result.current.mutate({});
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['jobs'] });
  });

  it('does not invalidate on error', async () => {
    const client = makeClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
    rpcMock.mockResolvedValue({ data: null, error: { message: 'nope' } });
    const { result } = renderHook(
      () => useRpc('do_thing', { invalidate: [['jobs']] }),
      { wrapper: wrapperWith(client) },
    );

    result.current.mutate({});
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(invalidateSpy).not.toHaveBeenCalled();
  });
});
