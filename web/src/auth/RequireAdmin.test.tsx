import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { RequireAdmin } from './RequireAdmin';

const useAuthMock = vi.fn();
vi.mock('./AuthProvider', () => ({ useAuth: () => useAuthMock() }));

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/recipes" element={<div>recipes-page</div>} />
        <Route element={<RequireAdmin />}>
          <Route path="/taxonomy" element={<div>taxonomy-page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('RequireAdmin', () => {
  it('renders child route when user is admin', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, isAdmin: true, loading: false });
    renderAt('/taxonomy');
    expect(screen.getByText('taxonomy-page')).toBeInTheDocument();
  });

  it('redirects to /recipes when authed but not admin', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, isAdmin: false, loading: false });
    renderAt('/taxonomy');
    expect(screen.getByText('recipes-page')).toBeInTheDocument();
  });

  it('renders nothing while loading', () => {
    useAuthMock.mockReturnValue({ user: null, isAdmin: false, loading: true });
    renderAt('/taxonomy');
    expect(screen.queryByText('taxonomy-page')).toBeNull();
    expect(screen.queryByText('recipes-page')).toBeNull();
  });
});
