import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fetchOpenReviews } from './useOpenReviews';

const queryTableMock = vi.fn();
vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  queryTable: (...args: unknown[]) => queryTableMock(...args),
}));

beforeEach(() => {
  queryTableMock.mockReset();
});

describe('fetchOpenReviews', () => {
  it('reads a page of open human_reviews rows oldest first', async () => {
    queryTableMock.mockResolvedValue({
      rows: [{ id: 1, entity_kind: 'ingredient_name', entity_id: 'gin', stage: 'map-ingredient', state: 'open', origin: 'human_flag', payload: null, note: null }],
      total: 137,
    });
    const { rows, total } = await fetchOpenReviews(1, 50);
    expect(queryTableMock).toHaveBeenCalledWith(expect.objectContaining({
      table: 'human_reviews',
      filters: [{ col: 'state', op: 'eq', value: 'open' }],
      order: { col: 'created_at', asc: true },
      limit: 50,
      offset: 0,
    }));
    expect(rows).toHaveLength(1);
    expect(rows[0].entity_id).toBe('gin');
    expect(total).toBe(137);
  });

  it('requests the right offset for a later page', async () => {
    queryTableMock.mockResolvedValue({ rows: [], total: 137 });
    await fetchOpenReviews(3, 50);
    expect(queryTableMock).toHaveBeenCalledWith(expect.objectContaining({ limit: 50, offset: 100 }));
  });

  it('throws on an API error', async () => {
    queryTableMock.mockRejectedValue(new Error('denied'));
    await expect(fetchOpenReviews()).rejects.toThrow('denied');
  });
});
