import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const queryTableMock = vi.fn();
vi.mock('../../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api')>()),
  queryTable: (...args: unknown[]) => queryTableMock(...args),
}));
import { usePagedQuery } from './usePagedQuery';

type Row = { id: number; name: string };

function wrapperWith(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

beforeEach(() => {
  queryTableMock.mockReset();
});

describe('usePagedQuery', () => {
  it('posts {table, select, filters, order, limit, offset} and returns rows+total', async () => {
    const rows: Row[] = [{ id: 1, name: 'a' }];
    queryTableMock.mockResolvedValue({ rows, total: 1 });

    const { result } = renderHook(
      () =>
        usePagedQuery<Row>({
          table: 't', select: 'id, name', order: { col: 'name', asc: true }, page: 1, pageSize: 50,
        }),
      { wrapper: wrapperWith(makeClient()) },
    );

    await waitFor(() => expect(result.current.status).toBe('loaded'));
    expect(queryTableMock).toHaveBeenCalledWith({
      table: 't', select: 'id, name', filters: [], order: { col: 'name', asc: true }, limit: 50, offset: 0,
    });
    expect(result.current.rows).toEqual(rows);
    expect(result.current.total).toBe(1);
  });

  it('requests the correct offset for page 3', async () => {
    queryTableMock.mockResolvedValue({ rows: [], total: 0 });
    const { result } = renderHook(
      () => usePagedQuery<Row>({ table: 't', select: '*', page: 3, pageSize: 50 }),
      { wrapper: wrapperWith(makeClient()) },
    );
    await waitFor(() => expect(result.current.status).toBe('loaded'));
    expect(queryTableMock).toHaveBeenCalledWith(expect.objectContaining({ limit: 50, offset: 100 }));
  });

  it('passes the filter list through in order', async () => {
    queryTableMock.mockResolvedValue({ rows: [], total: 0 });
    const filters = [
      { col: 'site', op: 'eq' as const, value: 'punch' },
      { col: 'state', op: 'in' as const, value: ['queued', 'running'] },
      { col: 'confidence', op: 'lt' as const, value: 0.5 },
    ];
    const { result } = renderHook(
      () => usePagedQuery<Row>({ table: 't', select: '*', filters, page: 1, pageSize: 50 }),
      { wrapper: wrapperWith(makeClient()) },
    );
    await waitFor(() => expect(result.current.status).toBe('loaded'));
    expect(queryTableMock).toHaveBeenCalledWith(expect.objectContaining({ filters }));
  });

  it('keeps previous rows visible (pending=true) while the next page is loading', async () => {
    let resolveSecond!: (v: { rows: Row[]; total: number }) => void;
    const secondPromise = new Promise<{ rows: Row[]; total: number }>((resolve) => {
      resolveSecond = resolve;
    });
    queryTableMock
      .mockResolvedValueOnce({ rows: [{ id: 1, name: 'a' }], total: 2 })
      .mockReturnValueOnce(secondPromise);

    const { result, rerender } = renderHook(
      ({ page }: { page: number }) => usePagedQuery<Row>({ table: 't', select: '*', page, pageSize: 1 }),
      { wrapper: wrapperWith(makeClient()), initialProps: { page: 1 } },
    );

    await waitFor(() => expect(result.current.status).toBe('loaded'));
    expect(result.current.rows).toEqual([{ id: 1, name: 'a' }]);
    expect(result.current.pending).toBe(false);

    rerender({ page: 2 });
    await waitFor(() => expect(result.current.pending).toBe(true));
    expect(result.current.rows).toEqual([{ id: 1, name: 'a' }]);
    expect(result.current.status).toBe('loaded');

    resolveSecond({ rows: [{ id: 2, name: 'b' }], total: 2 });
    await waitFor(() => expect(result.current.pending).toBe(false));
    expect(result.current.rows).toEqual([{ id: 2, name: 'b' }]);
  });

  it('reports status=error when the request fails', async () => {
    queryTableMock.mockRejectedValue(new Error('nope'));
    const { result } = renderHook(
      () => usePagedQuery<Row>({ table: 't', select: '*', page: 1, pageSize: 50 }),
      { wrapper: wrapperWith(makeClient()) },
    );
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.rows).toEqual([]);
  });
});
