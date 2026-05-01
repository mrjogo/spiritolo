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

export const TOP_LEVEL_ALLOWLIST: readonly string[] = [
  'whiskey',
  'gin',
  'rum',
  'brandy',
  'vodka',
  'tequila',
  'mezcal',
  'vermouth',
  'amaro',
  'bitters',
  'liqueur',
  'fortified_wine',
  'dairy',
  'syrup',
  'mixer',
  'fresh_produce',
  'citrus',
  'cranberry',
  'pineapple',
];

export function isOrphan(node: TaxonomyViewRow): boolean {
  if (node.parent_ids.length > 0) return false;
  return !TOP_LEVEL_ALLOWLIST.includes(node.slug);
}

export function matchesQuery(node: TaxonomyViewRow, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === '') return true;
  if (node.slug.toLowerCase().includes(q)) return true;
  if (node.display_name.toLowerCase().includes(q)) return true;
  return node.aliases.some((a) => a.toLowerCase().includes(q));
}
