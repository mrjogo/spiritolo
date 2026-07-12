// Thin alias of the existing useIsAdmin. /ops routes still nest under the
// existing <RequireAdmin> guard — this is not a new auth surface, just the
// name every /ops hook/view imports.
export { useIsAdmin as useAdminGate } from '../../auth/useIsAdmin';
