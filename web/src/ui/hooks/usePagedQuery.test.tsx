import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../../supabase', () => ({ supabase: { from: vi.fn() } }));
import { supabase } from '../../supabase';
import { usePagedQuery } from './usePagedQuery';

type Row = { id: number; name: string };

function makeChain(rows: Row[], count: number, error: unknown = null) {
  const calls: { op: string; args: unknown[] }[] = [];
  const range = vi.fn().mockImplementation((...args: unknown[]) => {
    calls.push({ op: 'range', args });
    return Promise.resolve({ data: rows, count, error });
  });
  const chain = {
    eq: vi.fn((...args: unknown[]) => { calls.push({ op: 'eq', args }); return chain; }),
    in: vi.fn((...args: unknown[]) => { calls.push({ op: 'in', args }); return chain; }),
    lt: vi.fn((...args: unknown[]) => { calls.push({ op: 'lt', args }); return chain; }),
    order: vi.fn((...args: unknown[]) => { calls.push({ op: 'order', args }); return chain; }),
    range,
  };
  const select = vi.fn((...args: unknown[]) => { calls.push({ op: 'select', args }); return chain; });
  (supabase.from as unknown as ReturnType<typeof vi.fn>).mockReturnValue({ select });
  return { select, chain, range, calls };
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
  vi.clearAllMocks();
});

describe('usePagedQuery', () => {
  it('requests select(sel, {count: exact}).order(...).range(from, to) and returns rows+total', async () => {
    const rows: Row[] = [{ id: 1, name: 'a' }];
    const { select, range, chain } = makeChain(rows, 1);

    const { result } = renderHook(
      () =>
        usePagedQuery<Row>({
          table: 'recipe_docs',
          select: 'id, name',
          order: { col: 'name' },
          page: 1,
          pageSize: 50,
        }),
      { wrapper: wrapperWith(makeClient()) },
    );

    await waitFor(() => expect(result.current.status).toBe('loaded'));
    expect(select).toHaveBeenCalledWith('id, name', { count: 'exact' });
    expect(chain.order).toHaveBeenCalledWith('name', { ascending: true });
    expect(range).toHaveBeenCalledWith(0, 49);
    expect(result.current.rows).toEqual(rows);
    expect(result.current.total).toBe(1);
  });

  it('requests the correct range for page 3', async () => {
    const { range } = makeChain([], 0);
    const { result } = renderHook(
      () => usePagedQuery<Row>({ table: 't', select: '*', page: 3, pageSize: 50 }),
      { wrapper: wrapperWith(makeClient()) },
    );
    await waitFor(() => expect(result.current.status).toBe('loaded'));
    expect(range).toHaveBeenCalledWith(100, 149);
  });

  it('applies a PostgrestFilter[] as .eq/.in/.lt calls in order', async () => {
    const { chain } = makeChain([], 0);
    const { result } = renderHook(
      () =>
        usePagedQuery<Row>({
          table: 't',
          select: '*',
          filters: [
            { col: 'site', op: 'eq', value: 'punch' },
            { col: 'state', op: 'in', value: ['queued', 'running'] },
            { col: 'confidence', op: 'lt', value: 0.5 },
          ],
          page: 1,
          pageSize: 50,
        }),
      { wrapper: wrapperWith(makeClient()) },
    );
    await waitFor(() => expect(result.current.status).toBe('loaded'));
    expect(chain.eq).toHaveBeenNthCalledWith(1, 'site', 'punch');
    expect(chain.in).toHaveBeenNthCalledWith(1, 'state', ['queued', 'running']);
    expect(chain.lt).toHaveBeenNthCalledWith(1, 'confidence', 0.5);
  });

  it('keeps previous rows visible (pending=true) while the next page is loading', async () => {
    let resolveSecond!: (v: { data: Row[]; count: number; error: null }) => void;
    const secondPromise = new Promise<{ data: Row[]; count: number; error: null }>((resolve) => {
      resolveSecond = resolve;
    });
    const range = vi
      .fn()
      .mockResolvedValueOnce({ data: [{ id: 1, name: 'a' }], count: 2, error: null })
      .mockReturnValueOnce(secondPromise);
    const chain = {
      eq: vi.fn(() => chain),
      in: vi.fn(() => chain),
      lt: vi.fn(() => chain),
      order: vi.fn(() => chain),
      range,
    };
    const select = vi.fn(() => chain);
    (supabase.from as unknown as ReturnType<typeof vi.fn>).mockReturnValue({ select });

    const { result, rerender } = renderHook(
      ({ page }: { page: number }) =>
        usePagedQuery<Row>({ table: 't', select: '*', page, pageSize: 1 }),
      { wrapper: wrapperWith(makeClient()), initialProps: { page: 1 } },
    );

    await waitFor(() => expect(result.current.status).toBe('loaded'));
    expect(result.current.rows).toEqual([{ id: 1, name: 'a' }]);
    expect(result.current.pending).toBe(false);

    rerender({ page: 2 });
    await waitFor(() => expect(result.current.pending).toBe(true));
    // Previous page's rows are still visible while pending.
    expect(result.current.rows).toEqual([{ id: 1, name: 'a' }]);

    resolveSecond({ data: [{ id: 2, name: 'b' }], count: 2, error: null });
    await waitFor(() => expect(result.current.pending).toBe(false));
    expect(result.current.rows).toEqual([{ id: 2, name: 'b' }]);
  });
});
