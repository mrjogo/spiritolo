export type TaxonomyRole = 'brand' | 'expression' | 'substance' | 'unknown';

export interface TaxonomyViewRow {
  id: number;
  slug: string;
  display_name: string;
  role: 'brand' | 'expression' | null;
  role_default: 'brand' | 'expression' | 'substance' | null;
  is_cluster_node: boolean;
  is_defining_garnish: boolean;
  parent_ids: number[];
  child_ids: number[];
  aliases: string[];
  recipe_count: number;
}

export interface TaxonomyNode extends TaxonomyViewRow {}

export interface TaxonomyLink {
  source: number;
  target: number;
}

export function effectiveRole(node: TaxonomyViewRow): TaxonomyRole {
  return (node.role ?? node.role_default ?? 'unknown') as TaxonomyRole;
}

export function viewRowsToGraph(rows: TaxonomyViewRow[]): {
  nodes: TaxonomyNode[];
  links: TaxonomyLink[];
} {
  const nodes: TaxonomyNode[] = rows.map((r) => ({ ...r }));
  const links: TaxonomyLink[] = [];
  for (const row of rows) {
    for (const childId of row.child_ids) {
      links.push({ source: row.id, target: childId });
    }
  }
  return { nodes, links };
}
