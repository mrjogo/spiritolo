import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AuthCallback } from './AuthCallback';

const useAuthMock = vi.fn();
vi.mock('../auth/AuthProvider', () => ({ useAuth: () => useAuthMock() }));

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route path="/recipes" element={<div>recipes-page</div>} />
        <Route path="/recipes/:id" element={<div>detail-page</div>} />
        <Route path="/login" element={<div>login-page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('AuthCallback', () => {
  it('shows a working message while auth is still loading', () => {
    useAuthMock.mockReturnValue({ user: null, loading: true });
    renderAt('/auth/callback?next=%2Frecipes');
    expect(screen.getByText(/signing you in/i)).toBeInTheDocument();
  });

  it('navigates to ?next= once user appears', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, loading: false });
    renderAt('/auth/callback?next=%2Frecipes%2Fabc');
    expect(screen.getByText('detail-page')).toBeInTheDocument();
  });

  it('falls back to /recipes when ?next= missing', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, loading: false });
    renderAt('/auth/callback');
    expect(screen.getByText('recipes-page')).toBeInTheDocument();
  });

  it('navigates to /login if loading finishes with no user (link expired/invalid)', () => {
    useAuthMock.mockReturnValue({ user: null, loading: false });
    renderAt('/auth/callback');
    expect(screen.getByText('login-page')).toBeInTheDocument();
  });
});
