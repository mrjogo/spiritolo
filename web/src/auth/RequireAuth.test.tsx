import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useSearchParams } from 'react-router-dom';
import { RequireAuth } from './RequireAuth';

const useAuthMock = vi.fn();
vi.mock('./AuthProvider', () => ({ useAuth: () => useAuthMock() }));

function LoginSpy() {
  const [params] = useSearchParams();
  return <div>login-page next={params.get('next') ?? 'none'}</div>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<RequireAuth />}>
          <Route path="/recipes" element={<div>recipes-page</div>} />
        </Route>
        <Route path="/login" element={<LoginSpy />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('RequireAuth', () => {
  it('renders nothing while loading', () => {
    useAuthMock.mockReturnValue({ user: null, loading: true });
    renderAt('/recipes');
    expect(screen.queryByText('recipes-page')).toBeNull();
    expect(screen.queryByText(/login-page/)).toBeNull();
  });

  it('renders child route when user is present', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, loading: false });
    renderAt('/recipes');
    expect(screen.getByText('recipes-page')).toBeInTheDocument();
  });

  it('redirects to /login with the encoded next param when no user', () => {
    useAuthMock.mockReturnValue({ user: null, loading: false });
    renderAt('/recipes?foo=bar');
    expect(
      screen.getByText('login-page next=/recipes?foo=bar'),
    ).toBeInTheDocument();
  });
});
