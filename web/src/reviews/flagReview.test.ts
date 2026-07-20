import { describe, it, expect, vi, beforeEach } from 'vitest';
import { flagReview, resolveReview, dismissReview } from './flagReview';

const rpcMock = vi.fn();
vi.mock('../supabase', () => ({
  supabase: { rpc: (...args: unknown[]) => rpcMock(...args) },
}));

beforeEach(() => {
  rpcMock.mockReset();
  rpcMock.mockResolvedValue({ data: null, error: null });
});

describe('flagReview', () => {
  it("calls rpc('flag_review', {p_entity_kind,p_entity_id,p_stage,p_note}) and returns the new id", async () => {
    rpcMock.mockResolvedValue({ data: 123, error: null });
    const id = await flagReview({
      entityKind: 'recipe',
      entityId: '42',
      stage: 'map-ingredient',
      note: 'looks off',
    });
    expect(rpcMock).toHaveBeenCalledWith('flag_review', {
      p_entity_kind: 'recipe',
      p_entity_id: '42',
      p_stage: 'map-ingredient',
      p_note: 'looks off',
    });
    expect(id).toBe(123);
  });

  it('passes p_note: null when note is omitted', async () => {
    rpcMock.mockResolvedValue({ data: 1, error: null });
    await flagReview({ entityKind: 'ingredient', entityId: 'gin', stage: 'parse-ingredients' });
    expect(rpcMock).toHaveBeenCalledWith('flag_review', {
      p_entity_kind: 'ingredient',
      p_entity_id: 'gin',
      p_stage: 'parse-ingredients',
      p_note: null,
    });
  });

  it('throws when the rpc returns an error', async () => {
    rpcMock.mockResolvedValue({ data: null, error: { message: 'boom' } });
    await expect(
      flagReview({ entityKind: 'recipe', entityId: '1', stage: 'map-ingredient' }),
    ).rejects.toEqual({ message: 'boom' });
  });
});

describe('resolveReview', () => {
  it("calls rpc('resolve_review', {p_id,p_payload}) with the given payload", async () => {
    await resolveReview({ id: 7, payload: { fixed: true } });
    expect(rpcMock).toHaveBeenCalledWith('resolve_review', {
      p_id: 7,
      p_payload: { fixed: true },
    });
  });

  it('passes p_payload: null when payload is omitted', async () => {
    await resolveReview({ id: 8 });
    expect(rpcMock).toHaveBeenCalledWith('resolve_review', {
      p_id: 8,
      p_payload: null,
    });
  });

  it('does not send a p_dismiss key', async () => {
    await resolveReview({ id: 7, payload: null });
    const args = rpcMock.mock.calls[0][1] as Record<string, unknown>;
    expect(args).not.toHaveProperty('p_dismiss');
  });

  it('throws when the rpc returns an error', async () => {
    rpcMock.mockResolvedValue({ data: null, error: { message: 'nope' } });
    await expect(resolveReview({ id: 7 })).rejects.toEqual({ message: 'nope' });
  });
});

describe('dismissReview', () => {
  it("calls rpc('resolve_review', {p_id,p_dismiss:true})", async () => {
    await dismissReview(9);
    expect(rpcMock).toHaveBeenCalledWith('resolve_review', {
      p_id: 9,
      p_dismiss: true,
    });
  });

  it('does not send a p_payload key', async () => {
    await dismissReview(9);
    const args = rpcMock.mock.calls[0][1] as Record<string, unknown>;
    expect(args).not.toHaveProperty('p_payload');
  });

  it('throws when the rpc returns an error', async () => {
    rpcMock.mockResolvedValue({ data: null, error: { message: 'fail' } });
    await expect(dismissReview(9)).rejects.toEqual({ message: 'fail' });
  });
});
