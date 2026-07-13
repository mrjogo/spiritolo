import { NavLink, Outlet } from 'react-router-dom';

// The /ops console shell: a left nav plus the routed child. Sits under the
// existing RequireAuth -> AppLayout -> RequireAdmin nesting (see App.tsx),
// so this component owns only the ops-specific chrome, not auth.
export function OpsLayout() {
  return (
    <div className="ops">
      <nav aria-label="ops">
        <ul>
          <li>
            <NavLink to="/ops" end>
              Dashboard
            </NavLink>
          </li>
        </ul>
      </nav>
      <Outlet />
    </div>
  );
}
