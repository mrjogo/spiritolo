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
        </ul>
      </nav>
      <Outlet />
    </div>
  );
}
