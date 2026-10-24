import { describe, it, expect, vi, beforeEach } from 'vitest';
import { flagReview, resolveReview, dismissReview } from './flagReview';

const apiMock = vi.fn();
vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  api: (...args: unknown[]) => apiMock(...args),
}));

beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockResolvedValue({ ok: true });
});

describe('flagReview', () => {
  it('posts the flag and returns the new review id', async () => {
    apiMock.mockResolvedValue({ id: 123 });
    const id = await flagReview({ entityKind: 'recipe', entityId: '42', stage: 'map-ingredient', note: 'looks off' });
    expect(apiMock).toHaveBeenCalledWith('/api/ops/reviews/flag', {
      body: { entity_kind: 'recipe', entity_id: '42', stage: 'map-ingredient', note: 'looks off' },
    });
    expect(id).toBe(123);
  });

  it('sends note: null when the note is omitted', async () => {
    apiMock.mockResolvedValue({ id: 1 });
    await flagReview({ entityKind: 'ingredient', entityId: 'gin', stage: 'parse-ingredients' });
    expect(apiMock).toHaveBeenCalledWith('/api/ops/reviews/flag', {
      body: { entity_kind: 'ingredient', entity_id: 'gin', stage: 'parse-ingredients', note: null },
    });
  });

  it('propagates an API failure', async () => {
    apiMock.mockRejectedValue(new Error('boom'));
    await expect(flagReview({ entityKind: 'recipe', entityId: '1', stage: 'map-ingredient' })).rejects.toThrow('boom');
  });
});

describe('resolveReview', () => {
  it('posts the payload to the resolve endpoint', async () => {
    await resolveReview({ id: 7, payload: { fixed: true } });
    expect(apiMock).toHaveBeenCalledWith('/api/ops/reviews/7/resolve', { body: { payload: { fixed: true } } });
  });

  it('sends payload: null when omitted', async () => {
    await resolveReview({ id: 7 });
    expect(apiMock).toHaveBeenCalledWith('/api/ops/reviews/7/resolve', { body: { payload: null } });
  });
});

describe('dismissReview', () => {
  it('posts to the dismiss endpoint', async () => {
    await dismissReview(9);
    expect(apiMock).toHaveBeenCalledWith('/api/ops/reviews/9/dismiss', { method: 'POST' });
  });
});
