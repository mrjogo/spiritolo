import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { Landing } from './Landing';

const useAuthMock = vi.fn();
vi.mock('../auth/AuthProvider', () => ({ useAuth: () => useAuthMock() }));

function renderApp() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/recipes" element={<div>recipes-page</div>} />
        <Route path="/login" element={<div>login-page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Landing', () => {
  it('renders title and image when logged out, with no sign-in affordance', () => {
    useAuthMock.mockReturnValue({ user: null, loading: false });
    renderApp();
    expect(screen.getByRole('heading', { name: /spiritolo/i })).toBeInTheDocument();
    expect(screen.getByRole('img')).toBeInTheDocument();
    // No links anywhere on the page — sign-in is direct-URL-only.
    expect(screen.queryAllByRole('link')).toHaveLength(0);
  });

  it('renders nothing visible while auth is loading', () => {
    useAuthMock.mockReturnValue({ user: null, loading: true });
    renderApp();
    expect(screen.queryByRole('heading', { name: /spiritolo/i })).toBeNull();
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('redirects to /recipes when already logged in', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, loading: false });
    renderApp();
    expect(screen.getByText('recipes-page')).toBeInTheDocument();
  });
});
