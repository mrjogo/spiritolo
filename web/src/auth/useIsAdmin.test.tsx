import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useIsAdmin, isAdminQueryKey } from './useIsAdmin';

const useAuthMock = vi.fn();
const profileSelectMock = vi.fn();

vi.mock('./AuthProvider', () => ({ useAuth: () => useAuthMock() }));
vi.mock('../supabase', () => ({
  supabase: {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    from: (_table: string) => ({
      select: () => ({
        eq: () => ({ maybeSingle: () => profileSelectMock() }),
      }),
    }),
  },
}));

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
}

function wrapperWith(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

beforeEach(() => {
  useAuthMock.mockReset();
  profileSelectMock.mockReset();
});

describe('useIsAdmin', () => {
  it('returns isLoading=true while session is loading', () => {
    useAuthMock.mockReturnValue({ user: null, loading: true });
    const { result } = renderHook(() => useIsAdmin(), {
      wrapper: wrapperWith(makeClient()),
    });
    expect(result.current).toEqual({ isAdmin: false, isLoading: true });
  });

  it('returns isAdmin=false, isLoading=false when there is no user', () => {
    useAuthMock.mockReturnValue({ user: null, loading: false });
    const { result } = renderHook(() => useIsAdmin(), {
      wrapper: wrapperWith(makeClient()),
    });
    expect(result.current).toEqual({ isAdmin: false, isLoading: false });
    expect(profileSelectMock).not.toHaveBeenCalled();
  });

  it('fetches and returns the admin flag for a user', async () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, loading: false });
    profileSelectMock.mockResolvedValue({ data: { is_admin: true }, error: null });

    const { result } = renderHook(() => useIsAdmin(), {
      wrapper: wrapperWith(makeClient()),
    });

    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAdmin).toBe(true);
  });

  it('returns isAdmin=false when the profile row is missing', async () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, loading: false });
    profileSelectMock.mockResolvedValue({ data: null, error: null });

    const { result } = renderHook(() => useIsAdmin(), {
      wrapper: wrapperWith(makeClient()),
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAdmin).toBe(false);
  });

  it('serves a value from cache without re-fetching', async () => {
    const client = makeClient();
    client.setQueryData(isAdminQueryKey('u-1'), true);
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, loading: false });

    const { result } = renderHook(() => useIsAdmin(), {
      wrapper: wrapperWith(client),
    });
    expect(result.current).toEqual({ isAdmin: true, isLoading: false });
    expect(profileSelectMock).not.toHaveBeenCalled();
  });
});
