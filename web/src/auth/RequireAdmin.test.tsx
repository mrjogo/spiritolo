import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { RequireAdmin } from './RequireAdmin';

const useIsAdminMock = vi.fn();
vi.mock('./useIsAdmin', () => ({ useIsAdmin: () => useIsAdminMock() }));

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
    useIsAdminMock.mockReturnValue({ isAdmin: true, isLoading: false });
    renderAt('/taxonomy');
    expect(screen.getByText('taxonomy-page')).toBeInTheDocument();
  });

  it('redirects to /recipes when authed but not admin', () => {
    useIsAdminMock.mockReturnValue({ isAdmin: false, isLoading: false });
    renderAt('/taxonomy');
    expect(screen.getByText('recipes-page')).toBeInTheDocument();
  });

  it('renders nothing while loading', () => {
    useIsAdminMock.mockReturnValue({ isAdmin: false, isLoading: true });
    renderAt('/taxonomy');
    expect(screen.queryByText('taxonomy-page')).toBeNull();
    expect(screen.queryByText('recipes-page')).toBeNull();
  });
});
