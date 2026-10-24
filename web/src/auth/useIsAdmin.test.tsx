import { renderHook } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useIsAdmin } from './useIsAdmin';

const useAuthMock = vi.fn();
vi.mock('./AuthProvider', () => ({ useAuth: () => useAuthMock() }));

beforeEach(() => {
  useAuthMock.mockReset();
});

describe('useIsAdmin', () => {
  it('returns isLoading=true while the session is loading', () => {
    useAuthMock.mockReturnValue({ user: null, loading: true });
    expect(renderHook(() => useIsAdmin()).result.current).toEqual({ isAdmin: false, isLoading: true });
  });

  it('returns isAdmin=false when there is no user', () => {
    useAuthMock.mockReturnValue({ user: null, loading: false });
    expect(renderHook(() => useIsAdmin()).result.current).toEqual({ isAdmin: false, isLoading: false });
  });

  it('reads the admin flag off the session operator', () => {
    useAuthMock.mockReturnValue({ user: { id: 1, handle: 'r', display_name: 'R', is_admin: true }, loading: false });
    expect(renderHook(() => useIsAdmin()).result.current).toEqual({ isAdmin: true, isLoading: false });
    useAuthMock.mockReturnValue({ user: { id: 2, handle: 'g', display_name: 'G', is_admin: false }, loading: false });
    expect(renderHook(() => useIsAdmin()).result.current).toEqual({ isAdmin: false, isLoading: false });
  });
});
