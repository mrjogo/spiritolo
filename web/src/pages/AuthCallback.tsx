import { Navigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';

export function AuthCallback() {
  const { user, loading } = useAuth();
  const [params] = useSearchParams();
  const rawNext = params.get('next') || '';
  // Only accept same-origin relative paths to prevent open-redirect via ?next=.
  const next = rawNext.startsWith('/') && !rawNext.startsWith('//') ? rawNext : '/recipes';

  if (loading) {
    return (
      <main className="page page--auth-callback">
        <p>Signing you in…</p>
      </main>
    );
  }

  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={next} replace />;
}
