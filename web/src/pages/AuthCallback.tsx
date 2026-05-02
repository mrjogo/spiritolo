import { Navigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';

export function AuthCallback() {
  const { user, loading } = useAuth();
  const [params] = useSearchParams();
  const next = params.get('next') || '/recipes';

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
