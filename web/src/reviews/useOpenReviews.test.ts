import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fetchOpenReviews } from './useOpenReviews';

const { rangeMock, orderMock, eqMock, selectMock, fromMock } = vi.hoisted(() => {
  const rangeMock = vi.fn();
  const orderMock = vi.fn(() => ({ range: rangeMock }));
  const eqMock = vi.fn(() => ({ order: orderMock }));
  const selectMock = vi.fn(() => ({ eq: eqMock }));
  const fromMock = vi.fn(() => ({ select: selectMock }));
  return { rangeMock, orderMock, eqMock, selectMock, fromMock };
});
vi.mock('../supabase', () => ({ supabase: { from: fromMock } }));

beforeEach(() => {
  fromMock.mockClear();
  selectMock.mockClear();
  eqMock.mockClear();
  orderMock.mockClear();
  rangeMock.mockReset();
});

describe('fetchOpenReviews', () => {
  it('reads a page of open human_reviews rows with an exact count', async () => {
    rangeMock.mockResolvedValue({
      data: [{ id: 1, entity_kind: 'ingredient_name', entity_id: 'gin', stage: 'map', state: 'open', origin: 'human_flag', payload: null, note: null }],
      count: 137,
      error: null,
    });
    const { rows, total } = await fetchOpenReviews(1, 50);
    expect(fromMock).toHaveBeenCalledWith('human_reviews');
    expect(eqMock).toHaveBeenCalledWith('state', 'open');
    expect(rangeMock).toHaveBeenCalledWith(0, 49);
    expect(rows).toHaveLength(1);
    expect(rows[0].entity_id).toBe('gin');
    expect(total).toBe(137);
  });

  it('requests the right range for a later page', async () => {
    rangeMock.mockResolvedValue({ data: [], count: 137, error: null });
    await fetchOpenReviews(3, 50);
    expect(rangeMock).toHaveBeenCalledWith(100, 149);
  });

  it('throws on a supabase error', async () => {
    rangeMock.mockResolvedValue({ data: null, count: null, error: new Error('denied') });
    await expect(fetchOpenReviews()).rejects.toThrow('denied');
  });
});
