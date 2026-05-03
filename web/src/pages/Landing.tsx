import { Link, Navigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';

export function Landing() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) return <Navigate to="/recipes" replace />;

  return (
    <main className="page page--landing">
      <div className="landing__hero">
        <img
          src="/spiritolo.jpg"
          alt="Champagne being poured into a coupe glass"
          className="landing__image"
        />
        <h1 className="landing__title">Spiritolo</h1>
      </div>
      <Link to="/login" className="landing__signin">
        Sign in
      </Link>
    </main>
  );
}
