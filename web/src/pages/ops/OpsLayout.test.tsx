import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { RequireAdmin } from '../../auth/RequireAdmin';
import { OpsLayout } from './OpsLayout';

const useIsAdminMock = vi.fn();
vi.mock('../../auth/useIsAdmin', () => ({ useIsAdmin: () => useIsAdminMock() }));

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/recipes" element={<div>recipes-page</div>} />
        <Route element={<RequireAdmin />}>
          <Route path="/ops" element={<OpsLayout />}>
            <Route index element={<div>dashboard-child</div>} />
          </Route>
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('<OpsLayout>', () => {
  it('redirects a non-admin away from /ops (reusing the useIsAdmin gate)', () => {
    useIsAdminMock.mockReturnValue({ isAdmin: false, isLoading: false });
    renderAt('/ops');
    expect(screen.getByText('recipes-page')).toBeInTheDocument();
    expect(screen.queryByText('dashboard-child')).not.toBeInTheDocument();
  });

  it('renders the left nav and the Outlet child for an admin', () => {
    useIsAdminMock.mockReturnValue({ isAdmin: true, isLoading: false });
    renderAt('/ops');
    expect(screen.getByRole('navigation', { name: /ops/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /dashboard/i })).toBeInTheDocument();
    expect(screen.getByText('dashboard-child')).toBeInTheDocument();
  });

  it('links to every /ops DB browser', () => {
    useIsAdminMock.mockReturnValue({ isAdmin: true, isLoading: false });
    renderAt('/ops');
    expect(screen.getByRole('link', { name: /recipes/i })).toHaveAttribute('href', '/ops/recipes');
    expect(screen.getByRole('link', { name: /stage runs/i })).toHaveAttribute('href', '/ops/stage-runs');
    expect(screen.getByRole('link', { name: /audit log/i })).toHaveAttribute('href', '/ops/audit-log');
    expect(screen.getByRole('link', { name: /clusters/i })).toHaveAttribute('href', '/ops/clusters');
    expect(screen.getByRole('link', { name: /exports/i })).toHaveAttribute('href', '/ops/exports');
  });
});
