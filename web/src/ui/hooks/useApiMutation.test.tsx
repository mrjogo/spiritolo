import { describe, it, expect, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useApiMutation } from './useApiMutation';
import { ApiError } from '../../api';

function wrapperWith(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

describe('useApiMutation', () => {
  it('runs the call with the args and exposes its result', async () => {
    const fn = vi.fn(async (a: { id: number }) => ({ ok: a.id }));
    const { result } = renderHook(() => useApiMutation(fn), { wrapper: wrapperWith(makeClient()) });
    result.current.mutate({ id: 1 });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ ok: 1 });
    expect(fn).toHaveBeenCalledWith({ id: 1 });
  });

  it('surfaces an ApiError from the call', async () => {
    const fn = vi.fn(async () => { throw new ApiError(409, 'conflict'); });
    const { result } = renderHook(() => useApiMutation(fn), { wrapper: wrapperWith(makeClient()) });
    result.current.mutate(undefined);
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(ApiError);
    expect(result.current.error?.status).toBe(409);
  });

  it('invalidates the given query keys only on success', async () => {
    const client = makeClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
    const ok = renderHook(() => useApiMutation(async () => 1, { invalidate: [['jobs']] }), { wrapper: wrapperWith(client) });
    ok.result.current.mutate(undefined);
    await waitFor(() => expect(ok.result.current.isSuccess).toBe(true));
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['jobs'] });

    invalidateSpy.mockClear();
    const bad = renderHook(
      () => useApiMutation(async () => { throw new ApiError(500, 'x'); }, { invalidate: [['jobs']] }),
      { wrapper: wrapperWith(client) },
    );
    bad.result.current.mutate(undefined);
    await waitFor(() => expect(bad.result.current.isError).toBe(true));
    expect(invalidateSpy).not.toHaveBeenCalled();
  });
});
