import { render, screen, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AuthProvider, useAuth } from './AuthProvider';

type AuthChangeHandler = (event: string, session: unknown) => void;
let authChangeHandler: AuthChangeHandler | null = null;
const getSessionMock = vi.fn();
const profileSelectMock = vi.fn();
const signOutMock = vi.fn(async () => ({ error: null }));

vi.mock('../supabase', () => ({
  supabase: {
    auth: {
      getSession: () => getSessionMock(),
      onAuthStateChange: (cb: AuthChangeHandler) => {
        authChangeHandler = cb;
        return { data: { subscription: { unsubscribe: () => {} } } };
      },
      signOut: () => signOutMock(),
    },
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    from: (_table: string) => ({
      select: () => ({
        eq: () => ({ maybeSingle: () => profileSelectMock() }),
      }),
    }),
  },
}));

function Probe() {
  const { user, isAdmin, loading } = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="user">{user?.id ?? 'none'}</span>
      <span data-testid="admin">{String(isAdmin)}</span>
    </div>
  );
}

beforeEach(() => {
  authChangeHandler = null;
  getSessionMock.mockReset();
  profileSelectMock.mockReset();
  signOutMock.mockClear();
});

describe('AuthProvider', () => {
  it('exposes loading=true on first render and user=null after empty session', async () => {
    getSessionMock.mockResolvedValue({ data: { session: null } });

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    expect(screen.getByTestId('loading').textContent).toBe('true');
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('user').textContent).toBe('none');
    expect(screen.getByTestId('admin').textContent).toBe('false');
  });

  it('hydrates user from initial session and fetches is_admin from profiles', async () => {
    getSessionMock.mockResolvedValue({
      data: { session: { user: { id: 'u-1' } } },
    });
    profileSelectMock.mockResolvedValue({ data: { is_admin: true }, error: null });

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('user').textContent).toBe('u-1');
    expect(screen.getByTestId('admin').textContent).toBe('true');
  });

  it('updates user and re-fetches is_admin when auth state changes', async () => {
    getSessionMock.mockResolvedValue({ data: { session: null } });

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('user').textContent).toBe('none');

    profileSelectMock.mockResolvedValue({ data: { is_admin: false }, error: null });
    await act(async () => {
      authChangeHandler!('SIGNED_IN', { user: { id: 'u-2' } });
    });

    await waitFor(() => expect(screen.getByTestId('user').textContent).toBe('u-2'));
    expect(screen.getByTestId('admin').textContent).toBe('false');
  });
});
