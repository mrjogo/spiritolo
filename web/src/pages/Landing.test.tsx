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
  it('renders title, image, and a sign-in link when logged out', () => {
    useAuthMock.mockReturnValue({ user: null, loading: false });
    renderApp();
    expect(screen.getByRole('heading', { name: /spiritolo/i })).toBeInTheDocument();
    expect(screen.getByRole('img')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /sign in/i })).toHaveAttribute(
      'href',
      '/login',
    );
  });

  it('renders nothing visible while auth is loading', () => {
    useAuthMock.mockReturnValue({ user: null, loading: true });
    renderApp();
    expect(screen.queryByRole('heading', { name: /spiritolo/i })).toBeNull();
  });

  it('redirects to /recipes when already logged in', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, loading: false });
    renderApp();
    expect(screen.getByText('recipes-page')).toBeInTheDocument();
  });
});
