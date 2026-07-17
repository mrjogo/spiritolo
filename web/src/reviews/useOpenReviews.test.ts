import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fetchOpenReviews } from './useOpenReviews';

const orderMock = vi.fn();
const eqMock = vi.fn(() => ({ order: orderMock }));
const selectMock = vi.fn(() => ({ eq: eqMock }));
const fromMock = vi.fn(() => ({ select: selectMock }));
vi.mock('../supabase', () => ({
  supabase: { from: fromMock },
}));

beforeEach(() => {
  fromMock.mockClear();
  selectMock.mockClear();
  eqMock.mockClear();
  orderMock.mockReset();
});

describe('fetchOpenReviews', () => {
  it("reads open stage_reviews rows", async () => {
    orderMock.mockResolvedValue({
      data: [{ id: 1, entity_kind: 'ingredient_name', entity_id: 'gin', stage: 'map', state: 'open', origin: 'human_flag', payload: null, note: null }],
      error: null,
    });
    const rows = await fetchOpenReviews();
    expect(fromMock).toHaveBeenCalledWith('stage_reviews');
    expect(eqMock).toHaveBeenCalledWith('state', 'open');
    expect(rows).toHaveLength(1);
    expect(rows[0].entity_id).toBe('gin');
  });

  it('throws on a supabase error', async () => {
    orderMock.mockResolvedValue({ data: null, error: new Error('denied') });
    await expect(fetchOpenReviews()).rejects.toThrow('denied');
  });
});
