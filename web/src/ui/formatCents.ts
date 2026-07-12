// Pulled out of CostBadge.tsx (which must export only the component, for
// react-refresh/only-export-components) but kept as its own tiny pure
// function so it's independently testable and reusable outside the badge
// (e.g. a raw cost column in DataTable).
export function formatCents(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return '—'; // em dash
  return `$${(cents / 100).toFixed(2)}`;
}
