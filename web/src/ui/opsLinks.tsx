import { Link } from 'react-router-dom';

// Cross-links between /ops browsers. Selection is carried in the URL (?sel= via
// SplitView), stage-run filters in ?stage/?outcome/?version, and the taxonomy
// graph focuses a node via ?node=<slug> — so a plain <Link> to these deep-links
// straight into the right detail/filter.
export const recipeHref = (id: string | number) => `/ops/recipes?sel=${id}`;
export const clusterHref = (key: string) => `/ops/clusters?sel=${encodeURIComponent(key)}`;
export const exportHref = (id: string | number) => `/ops/exports?sel=${id}`;
export const stageRunsHref = (stage: string) => `/ops/stage-runs?stage=${encodeURIComponent(stage)}`;
export const taxonomyHref = (slug: string) => `/taxonomy?node=${encodeURIComponent(slug)}`;

// The audit pk is `to_jsonb(row)->>'id'`, so it addresses the row's own detail
// for browsers keyed on a bigint id. Tables without an addressable detail (or a
// non-id pk) return null and render as plain text.
export function auditRowHref(table: string, pk: string): string | null {
  switch (table) {
    case 'recipes':
      return recipeHref(pk);
    case 'recipe_exports':
      return exportHref(pk);
    case 'stage_reviews':
      return '/ops/reviews';
    default:
      return null;
  }
}

// A review's entity → its detail, when it has one. recipe_ingredient ids are
// "recipe_id:position", so they resolve to the recipe. ingredient_name / page
// have no ops detail page and return null (rendered as plain text).
export function reviewEntityHref(kind: string, id: string): string | null {
  switch (kind) {
    case 'recipe':
      return recipeHref(id);
    case 'recipe_ingredient':
      return recipeHref(id.split(':')[0]);
    case 'cluster':
      return clusterHref(id);
    default:
      return null;
  }
}

// A Link that doesn't trigger the surrounding clickable table row. Use for
// cross-links rendered inside a DataTable cell or a selectable list item.
export function CrossLink({
  to,
  children,
  title,
}: {
  to: string;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <Link className="ops-xlink" to={to} title={title} onClick={(e) => e.stopPropagation()}>
      {children}
    </Link>
  );
}
