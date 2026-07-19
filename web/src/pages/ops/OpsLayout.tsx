import { useEffect, useRef } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import './ops.css';

// Phone breakpoint — mirrors the max-width:640px block in ops.css, where the
// tab bar becomes a horizontal scroll strip.
const MOBILE_QUERY = '(max-width: 640px)';

// The /ops console shell: a left nav plus the routed child. Sits under the
// existing RequireAuth -> AppLayout -> RequireAdmin nesting (see App.tsx),
// so this component owns only the ops-specific chrome, not auth.
export function OpsLayout() {
  const navRef = useRef<HTMLElement>(null);
  const location = useLocation();

  // On a phone the tab bar is a single swipeable strip; keep the active tab in
  // view after navigating. Gated on the mobile media query — matchMedia is
  // undefined under jsdom, so this is inert in tests, and on desktop (where the
  // strip wraps and never scrolls) it's a no-op.
  useEffect(() => {
    if (!window.matchMedia?.(MOBILE_QUERY)?.matches) return;
    const active = navRef.current?.querySelector('a.active');
    active?.scrollIntoView({ inline: 'center', block: 'nearest' });
  }, [location.pathname]);

  return (
    <div className="ops">
      <nav aria-label="ops" ref={navRef}>
        <ul>
          <li>
            <NavLink to="/ops" end>
              Dashboard
            </NavLink>
          </li>
          <li>
            <NavLink to="/ops/runs">Runs</NavLink>
          </li>
          <li>
            <NavLink to="/ops/recipes">Recipes</NavLink>
          </li>
          <li>
            <NavLink to="/ops/stage-runs">Stage runs</NavLink>
          </li>
          <li>
            <NavLink to="/ops/audit-log">Audit log</NavLink>
          </li>
          <li>
            <NavLink to="/ops/clusters">Clusters</NavLink>
          </li>
          <li>
            <NavLink to="/ops/exports">Exports</NavLink>
          </li>
          <li>
            <NavLink to="/ops/reviews">Reviews</NavLink>
          </li>
        </ul>
      </nav>
      <div className="ops-content">
        <Outlet />
      </div>
    </div>
  );
}
