import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { Header } from './Header';

const useAuthMock = vi.fn();
const signOutMock = vi.fn(async () => {});
vi.mock('../auth/AuthProvider', () => ({
  useAuth: () => ({ ...useAuthMock(), signOut: signOutMock }),
}));

beforeEach(() => signOutMock.mockClear());

function renderHeader() {
  return render(
    <MemoryRouter initialEntries={['/recipes']}>
      <Routes>
        <Route path="/recipes" element={<Header />} />
        <Route path="/" element={<div>landing-page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Header', () => {
  it('shows Recipes link and Sign out for an authed non-admin', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, isAdmin: false, loading: false });
    renderHeader();
    expect(screen.getByRole('link', { name: /recipes/i })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /taxonomy/i })).toBeNull();
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /spiritolo/i })).toHaveAttribute('href', '/recipes');
  });

  it('shows Taxonomy link when isAdmin', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, isAdmin: true, loading: false });
    renderHeader();
    expect(screen.getByRole('link', { name: /taxonomy/i })).toBeInTheDocument();
  });

  it('clicking Sign out calls signOut and navigates to /', async () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, isAdmin: false, loading: false });
    const user = userEvent.setup();
    renderHeader();
    await user.click(screen.getByRole('button', { name: /sign out/i }));
    expect(signOutMock).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('landing-page')).toBeInTheDocument();
  });
});
