import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';

export function Header() {
  const { user, isAdmin, signOut } = useAuth();
  const navigate = useNavigate();

  async function onSignOut() {
    await signOut();
    navigate('/');
  }

  return (
    <header className="site-header">
      <Link to="/recipes" className="site-header__brand">SPIRITOLO</Link>
      <nav className="site-header__nav">
        <Link to="/recipes">Recipes</Link>
        {isAdmin && <Link to="/taxonomy">Taxonomy</Link>}
      </nav>
      {user && (
        <button type="button" onClick={onSignOut} className="site-header__signout">
          Sign out
        </button>
      )}
    </header>
  );
}
