import { render, screen, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './AuthProvider';

const apiMock = vi.fn();
vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  api: (...args: unknown[]) => apiMock(...args),
}));

function Probe() {
  const { user, loading, setupRequired, signOut } = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="user">{user?.handle ?? 'none'}</span>
      <span data-testid="setup">{String(setupRequired)}</span>
      <button onClick={() => void signOut()}>out</button>
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
  apiMock.mockReset();
});

describe('AuthProvider', () => {
  it('starts loading, then reports no user when /api/auth/me has no operator', async () => {
    apiMock.mockResolvedValue({ operator: null, setup_required: true });
    renderWithProviders();
    expect(screen.getByTestId('loading').textContent).toBe('true');
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('user').textContent).toBe('none');
    expect(screen.getByTestId('setup').textContent).toBe('true');
    expect(apiMock).toHaveBeenCalledWith('/api/auth/me');
  });

  it('hydrates the operator from /api/auth/me', async () => {
    apiMock.mockResolvedValue({ operator: { id: 1, handle: 'ruddick', display_name: 'R', is_admin: true }, setup_required: false });
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId('user').textContent).toBe('ruddick'));
  });

  it('treats a failed probe as signed out', async () => {
    apiMock.mockRejectedValue(new Error('offline'));
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('user').textContent).toBe('none');
  });

  it('signOut posts to /api/auth/logout, drops the user and clears the query cache', async () => {
    apiMock.mockResolvedValue({ operator: { id: 1, handle: 'ruddick', display_name: 'R', is_admin: true }, setup_required: false });
    const { client } = renderWithProviders();
    client.setQueryData(['anything'], 1);
    await waitFor(() => expect(screen.getByTestId('user').textContent).toBe('ruddick'));
    apiMock.mockResolvedValue({ ok: true });
    await act(async () => {
      screen.getByText('out').click();
    });
    await waitFor(() => expect(screen.getByTestId('user').textContent).toBe('none'));
    expect(apiMock).toHaveBeenCalledWith('/api/auth/logout', { method: 'POST' });
    expect(client.getQueryData(['anything'])).toBeUndefined();
  });
});
