import { describe, it, expect, vi } from 'vitest';

vi.mock('../../supabase', () => ({ supabase: { from: vi.fn() } }));

import { useAdminGate } from './useAdminGate';
import { useIsAdmin } from '../../auth/useIsAdmin';

describe('useAdminGate', () => {
  it('is referentially the existing useIsAdmin — no new auth surface', () => {
    expect(useAdminGate).toBe(useIsAdmin);
  });
});
