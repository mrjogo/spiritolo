import { describe, it, expect, vi } from 'vitest';
import { proposalsQueryKey, parentsQueryKey, flagReasonsQueryKey } from './queries';

describe('query keys', () => {
  it('proposalsQueryKey is stable', () => {
    expect(proposalsQueryKey()).toEqual(['proposals', 'pending']);
  });
  it('parentsQueryKey is stable', () => {
    expect(parentsQueryKey()).toEqual(['proposals', 'parents']);
  });
  it('flagReasonsQueryKey is stable', () => {
    expect(flagReasonsQueryKey()).toEqual(['flagReasons']);
  });
});

vi.mock('../../supabase', () => ({
  supabase: {
    from: vi.fn().mockReturnValue({
      select: vi.fn().mockReturnValue({
        order: vi.fn().mockResolvedValue({ data: [], error: null }),
      }),
    }),
  },
}));
