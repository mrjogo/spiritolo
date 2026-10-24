import { useAuth } from './AuthProvider';

// The admin flag rides on the session itself (/api/auth/me), so this is a pure
// read of the auth context — no extra query, no profiles table.
export function useIsAdmin(): { isAdmin: boolean; isLoading: boolean } {
  const { user, loading } = useAuth();
  if (loading) return { isAdmin: false, isLoading: true };
  return { isAdmin: Boolean(user?.is_admin), isLoading: false };
}
