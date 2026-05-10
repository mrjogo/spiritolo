export type TaxonomyRole = 'brand' | 'expression' | 'substance' | 'unknown';

export interface TaxonomyViewRow {
  id: number;
  slug: string;
  display_name: string;
  node_kind: 'brand' | 'expression' | null;
  default_role: string | null;
  is_cluster_node: boolean;
  is_defining_garnish: boolean;
  parent_ids: number[];
  child_ids: number[];
  aliases: string[];
  recipe_count: number;
}

export const LABEL_FONT = "9px 'Cinzel', serif";
export const LABEL_HEIGHT = 11;  // approx Cinzel cap+descender at 9px

let measureCtx: CanvasRenderingContext2D | null = null;
function getMeasureCtx(): CanvasRenderingContext2D {
  if (measureCtx) return measureCtx;
  const c = document.createElement('canvas');
  const ctx = c.getContext('2d');
  if (!ctx) throw new Error('canvas 2d context unavailable');
  ctx.font = LABEL_FONT;
  measureCtx = ctx;
  return ctx;
}

// Extends TaxonomyViewRow with label dimensions baked in for the simulation's
// collision shape. react-force-graph will mutate fx/fy/x/y/vx/vy at runtime.
export interface TaxonomyNode extends TaxonomyViewRow {
  labelW: number;
  labelH: number;
}

// Runtime view of a node — what react-force-graph actually mutates. Reads
// of x/y/vx/vy go through this; the lib's own GraphData type doesn't allow
// `null` on fx/fy, so those stay private to the pinning code.
type RuntimeNode = TaxonomyNode & {
  x?: number; y?: number;
  vx?: number; vy?: number;
};

export interface TaxonomyLink {
  source: number;
  target: number;
}

export function effectiveKind(node: TaxonomyViewRow): TaxonomyRole {
  return (node.node_kind ?? 'unknown') as TaxonomyRole;
}

export function viewRowsToGraph(
  rows: TaxonomyViewRow[],
  prev: TaxonomyNode[] = [],
): {
  nodes: TaxonomyNode[];
  links: TaxonomyLink[];
} {
  const ctx = getMeasureCtx();
  const prevById = new Map(prev.map((n) => [n.id, n as RuntimeNode]));
  const nodes: TaxonomyNode[] = rows.map((r) => {
    const prior = prevById.get(r.id);
    const carry: Partial<Pick<RuntimeNode, 'x' | 'y' | 'vx' | 'vy'>> = {};
    if (prior) {
      // Existing node: preserve simulation state so a rows update doesn't
      // cold-restart the canvas. Without this, every add/edit reshapes
      // the world from random positions.
      if (prior.x != null) carry.x = prior.x;
      if (prior.y != null) carry.y = prior.y;
      if (prior.vx != null) carry.vx = prior.vx;
      if (prior.vy != null) carry.vy = prior.vy;
    } else {
      // Brand-new node: seed near a known parent so it has valid coords on
      // the very next render. Lets the focus/pulse effects find the node
      // immediately instead of bailing on undefined x/y.
      for (const pid of r.parent_ids) {
        const p = prevById.get(pid);
        if (p?.x != null && p.y != null) {
          carry.x = p.x;
          carry.y = p.y;
          break;
        }
      }
    }
    return {
      ...r,
      ...carry,
      labelW: ctx.measureText(r.display_name).width,
      labelH: LABEL_HEIGHT,
    };
  });
  const links: TaxonomyLink[] = [];
  for (const row of rows) {
    for (const childId of row.child_ids) {
      links.push({ source: row.id, target: childId });
    }
  }
  return { nodes, links };
}


export function matchesQuery(node: TaxonomyViewRow, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === '') return true;
  if (node.slug.toLowerCase().includes(q)) return true;
  if (node.display_name.toLowerCase().includes(q)) return true;
  return node.aliases.some((a) => a.toLowerCase().includes(q));
}

export type FilterKey =
  | 'substance' | 'expression' | 'brand'
  | 'cluster' | 'orphan' | 'no aliases' | 'zero recipes';

export function rowMatchesFilters(
  row: TaxonomyViewRow,
  active: Set<FilterKey>,
): boolean {
  for (const f of active) {
    if (f === 'substance' || f === 'expression' || f === 'brand') {
      if (effectiveKind(row) !== f) return false;
      continue;
    }
    if (f === 'cluster' && !row.is_cluster_node) return false;
    if (f === 'orphan' && row.parent_ids.length > 0) return false;
    if (f === 'no aliases' && row.aliases.length > 0) return false;
    if (f === 'zero recipes' && row.recipe_count > 0) return false;
  }
  return true;
}

export interface NeighborSet {
  focused: TaxonomyViewRow;
  parents: TaxonomyViewRow[];
  children: TaxonomyViewRow[];
}

export function neighborsOf(
  node: TaxonomyViewRow,
  byId: Map<number, TaxonomyViewRow>,
): NeighborSet {
  const lookup = (id: number) => byId.get(id);
  const parents = node.parent_ids.map(lookup).filter((n): n is TaxonomyViewRow => !!n);
  const children = node.child_ids.map(lookup).filter((n): n is TaxonomyViewRow => !!n);
  return { focused: node, parents, children };
}

export interface RadialFocus {
  id: number;
  x: number;
  y: number;
}

export interface RadialNeighbor {
  id: number;
}

export function radialPositions(
  focused: RadialFocus,
  parents: RadialNeighbor[],
  children: RadialNeighbor[],
  radius: number,
): Map<number, { x: number; y: number }> {
  const out = new Map<number, { x: number; y: number }>();
  // Parents arc the top semicircle (-PI to 0); children arc the bottom (0 to PI).
  // t = (i+1)/(n+1) keeps every neighbor strictly inside the open arc, so
  // no parent lands at y=0 alongside the children's arc start.
  const placeArc = (
    list: RadialNeighbor[],
    arcStart: number,
    arcEnd: number,
  ) => {
    if (list.length === 0) return;
    const sorted = [...list].sort((a, b) => a.id - b.id);
    for (let i = 0; i < sorted.length; i++) {
      const t = (i + 1) / (sorted.length + 1);
      const angle = arcStart + t * (arcEnd - arcStart);
      out.set(sorted[i].id, {
        x: focused.x + radius * Math.cos(angle),
        y: focused.y + radius * Math.sin(angle),
      });
    }
  };
  placeArc(parents,  -Math.PI, 0);
  placeArc(children, 0, Math.PI);
  return out;
}
