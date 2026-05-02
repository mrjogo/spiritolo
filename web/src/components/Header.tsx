import { Link } from 'react-router-dom';

export function Header() {
  return (
    <header className="site-header">
      <Link to="/" className="site-header__brand">SPIRITOLO</Link>
      <nav className="site-header__nav">
        <Link to="/">Recipes</Link>
        <Link to="/taxonomy">Taxonomy</Link>
      </nav>
    </header>
  );
}
