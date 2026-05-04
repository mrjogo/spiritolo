import { Navigate, Outlet } from 'react-router-dom';
import { useIsAdmin } from './useIsAdmin';

export function RequireAdmin() {
  const { isAdmin, isLoading } = useIsAdmin();
  if (isLoading) return null;
  if (!isAdmin) return <Navigate to="/recipes" replace />;
  return <Outlet />;
}
