import { render, screen, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './AuthProvider';
import { isAdminQueryKey } from './useIsAdmin';

type AuthChangeHandler = (event: string, session: unknown) => void;
let authChangeHandler: AuthChangeHandler | null = null;
const signOutMock = vi.fn(async () => ({ error: null }));

vi.mock('../supabase', () => ({
  supabase: {
    auth: {
      onAuthStateChange: (cb: AuthChangeHandler) => {
        authChangeHandler = cb;
        return { data: { subscription: { unsubscribe: () => {} } } };
      },
      signOut: () => signOutMock(),
    },
  },
}));

function Probe() {
  const { user, loading } = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="user">{user?.id ?? 'none'}</span>
    </div>
  );
}

function renderWithProviders(client: QueryClient = new QueryClient()) {
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <AuthProvider>
          <Probe />
        </AuthProvider>
      </QueryClientProvider>,
    ),
  };
}

beforeEach(() => {
  authChangeHandler = null;
  signOutMock.mockClear();
});

describe('AuthProvider', () => {
  it('starts with loading=true and resolves to user=none on INITIAL_SESSION with null', async () => {
    renderWithProviders();
    expect(screen.getByTestId('loading').textContent).toBe('true');

    await act(async () => {
      authChangeHandler!('INITIAL_SESSION', null);
    });

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('user').textContent).toBe('none');
  });

  it('hydrates user from INITIAL_SESSION', async () => {
    renderWithProviders();

    await act(async () => {
      authChangeHandler!('INITIAL_SESSION', { user: { id: 'u-1' } });
    });

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('user').textContent).toBe('u-1');
  });

  it('updates user when SIGNED_IN fires after empty initial', async () => {
    renderWithProviders();

    await act(async () => {
      authChangeHandler!('INITIAL_SESSION', null);
    });
    await waitFor(() => expect(screen.getByTestId('user').textContent).toBe('none'));

    await act(async () => {
      authChangeHandler!('SIGNED_IN', { user: { id: 'u-2' } });
    });
    await waitFor(() => expect(screen.getByTestId('user').textContent).toBe('u-2'));
  });

  it('clears user and removes the isAdmin query cache on SIGNED_OUT', async () => {
    const client = new QueryClient();
    client.setQueryData(isAdminQueryKey('u-1'), true);
    renderWithProviders(client);

    await act(async () => {
      authChangeHandler!('INITIAL_SESSION', { user: { id: 'u-1' } });
    });
    await waitFor(() => expect(screen.getByTestId('user').textContent).toBe('u-1'));

    await act(async () => {
      authChangeHandler!('SIGNED_OUT', null);
    });
    await waitFor(() => expect(screen.getByTestId('user').textContent).toBe('none'));

    // Cached admin flag should have been removed.
    expect(client.getQueryData(isAdminQueryKey('u-1'))).toBeUndefined();
  });
});
