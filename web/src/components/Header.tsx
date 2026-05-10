import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';
import { useIsAdmin } from '../auth/useIsAdmin';

export function Header() {
  const { user, signOut } = useAuth();
  const { isAdmin, isLoading: adminLoading } = useIsAdmin();
  const navigate = useNavigate();

  async function onSignOut() {
    try {
      await signOut();
    } catch {
      // Sign-out errors are non-fatal; navigate to landing anyway to reset client state.
    }
    navigate('/');
  }

  return (
    <header className="site-header">
      <Link to="/recipes" className="site-header__brand">SPIRITOLO</Link>
      <nav className="site-header__nav">
        <Link to="/recipes">Recipes</Link>
        {!adminLoading && isAdmin && <Link to="/taxonomy">Taxonomy</Link>}
      </nav>
      {user && (
        <div className="site-header__user">
          {!adminLoading && isAdmin && (
            <span className="site-header__admin-chip">admin</span>
          )}
          <button type="button" onClick={onSignOut} className="site-header__signout">
            Sign out
          </button>
        </div>
      )}
    </header>
  );
}
