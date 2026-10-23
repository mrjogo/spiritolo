import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { Login } from './Login';

const apiMock = vi.fn();
const startAuthenticationMock = vi.fn();
const startRegistrationMock = vi.fn();
const useAuthMock = vi.fn();
const refreshMock = vi.fn(async () => {});

vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  api: (...args: unknown[]) => apiMock(...args),
}));
vi.mock('@simplewebauthn/browser', () => ({
  startAuthentication: (...args: unknown[]) => startAuthenticationMock(...args),
  startRegistration: (...args: unknown[]) => startRegistrationMock(...args),
}));
vi.mock('../auth/AuthProvider', () => ({ useAuth: () => useAuthMock() }));

beforeEach(() => {
  apiMock.mockReset();
  startAuthenticationMock.mockReset();
  startRegistrationMock.mockReset();
  refreshMock.mockClear();
  useAuthMock.mockReturnValue({ user: null, loading: false, setupRequired: false, refresh: refreshMock });
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/recipes" element={<div>recipes-page</div>} />
        <Route path="/recipes/:id" element={<div>detail-page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Login', () => {
  it('runs the passkey ceremony and lands on ?next=', async () => {
    const user = userEvent.setup();
    apiMock.mockImplementation(async (path: string) => {
      if (path === '/api/auth/login/options') return { challenge: 'abc', rpId: 'localhost' };
      if (path === '/api/auth/login/verify') return { operator: { id: 1 } };
      throw new Error(`unexpected ${path}`);
    });
    startAuthenticationMock.mockResolvedValue({ id: 'cred', response: {} });
    renderAt('/login?next=%2Frecipes%2Fabc');

    await user.click(screen.getByRole('button', { name: /sign in with passkey/i }));

    await waitFor(() => expect(screen.getByText('detail-page')).toBeInTheDocument());
    expect(startAuthenticationMock).toHaveBeenCalledWith({ optionsJSON: { challenge: 'abc', rpId: 'localhost' } });
    expect(apiMock).toHaveBeenCalledWith('/api/auth/login/verify', { body: { credential: { id: 'cred', response: {} } } });
    expect(refreshMock).toHaveBeenCalled();
  });

  it('ignores an off-origin ?next= and falls back to /recipes', async () => {
    const user = userEvent.setup();
    apiMock.mockResolvedValue({});
    startAuthenticationMock.mockResolvedValue({});
    renderAt('/login?next=//evil.example');
    await user.click(screen.getByRole('button', { name: /sign in with passkey/i }));
    expect(await screen.findByText('recipes-page')).toBeInTheDocument();
  });

  it('shows the error when the passkey prompt fails', async () => {
    const user = userEvent.setup();
    apiMock.mockResolvedValue({});
    startAuthenticationMock.mockRejectedValue(Object.assign(new Error('x'), { name: 'NotAllowedError' }));
    renderAt('/login');
    await user.click(screen.getByRole('button', { name: /sign in with passkey/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/cancelled/i);
  });

  it('offers first-time setup while no operator exists, registering a passkey', async () => {
    const user = userEvent.setup();
    useAuthMock.mockReturnValue({ user: null, loading: false, setupRequired: true, refresh: refreshMock });
    apiMock.mockImplementation(async (path: string) => {
      if (path === '/api/auth/register/options') return { challenge: 'reg' };
      if (path === '/api/auth/register/verify') return { operator: { id: 1 } };
      throw new Error(`unexpected ${path}`);
    });
    startRegistrationMock.mockResolvedValue({ id: 'new-cred' });
    renderAt('/login');

    await user.type(screen.getByLabelText(/handle/i), 'ruddick');
    await user.type(screen.getByLabelText(/display name/i), 'Ruddick');
    await user.click(screen.getByRole('button', { name: /create passkey/i }));

    await waitFor(() => expect(screen.getByText('recipes-page')).toBeInTheDocument());
    expect(apiMock).toHaveBeenCalledWith('/api/auth/register/options', { body: { handle: 'ruddick', display_name: 'Ruddick' } });
    expect(startRegistrationMock).toHaveBeenCalledWith({ optionsJSON: { challenge: 'reg' } });
  });
});
