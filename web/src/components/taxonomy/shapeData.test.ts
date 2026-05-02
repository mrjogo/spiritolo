import { describe, it, expect } from 'vitest';
import {
  effectiveKind,
  viewRowsToGraph,
  matchesQuery,
  rowMatchesFilters,
  neighborsOf,
  radialPositions,
} from './shapeData';
import type { FilterKey, TaxonomyViewRow } from './shapeData';

const baseRow: TaxonomyViewRow = {
  id: 1,
  slug: 'whiskey',
  display_name: 'Whiskey',
  node_kind: null,
  default_role: 'substance',
  is_cluster_node: true,
  is_defining_garnish: false,
  parent_ids: [],
  child_ids: [2, 3],
  aliases: ['whisky'],
  recipe_count: 12,
};

describe('effectiveKind', () => {
  it('returns node_kind when set', () => {
    expect(effectiveKind({ ...baseRow, node_kind: 'expression', default_role: null })).toBe('expression');
  });

  it('returns "unknown" when node_kind is null, regardless of default_role', () => {
    expect(effectiveKind({ ...baseRow, node_kind: null, default_role: 'modifier' })).toBe('unknown');
    expect(effectiveKind({ ...baseRow, node_kind: null, default_role: null })).toBe('unknown');
  });
});

describe('viewRowsToGraph', () => {
  it('returns nodes mirroring rows and links from child_ids', () => {
    const rows: TaxonomyViewRow[] = [
      { ...baseRow, id: 1, slug: 'whiskey', child_ids: [2] },
      { ...baseRow, id: 2, slug: 'rye_whiskey', parent_ids: [1], child_ids: [] },
    ];
    const { nodes, links } = viewRowsToGraph(rows);
    expect(nodes).toHaveLength(2);
    expect(nodes[0].id).toBe(1);
    expect(nodes[0].slug).toBe('whiskey');
    expect(links).toEqual([{ source: 1, target: 2 }]);
  });

  it('does not double-emit links derived from parent_ids', () => {
    const rows: TaxonomyViewRow[] = [
      { ...baseRow, id: 1, slug: 'whiskey', child_ids: [2] },
      { ...baseRow, id: 2, slug: 'rye_whiskey', parent_ids: [1], child_ids: [] },
    ];
    const { links } = viewRowsToGraph(rows);
    expect(links).toHaveLength(1);
  });

  it('populates labelW and labelH on each node', () => {
    const rows: TaxonomyViewRow[] = [
      { ...baseRow, id: 1, slug: 'whiskey', display_name: 'Whiskey', child_ids: [] },
    ];
    const { nodes } = viewRowsToGraph(rows);
    expect(nodes[0].labelW).toBeGreaterThan(0);
    expect(nodes[0].labelH).toBeGreaterThan(0);
  });
});


describe('matchesQuery', () => {
  it('returns true for a substring of slug', () => {
    expect(matchesQuery({ ...baseRow, slug: 'rye_whiskey' }, 'rye')).toBe(true);
  });

  it('returns true for a substring of display_name', () => {
    expect(matchesQuery({ ...baseRow, display_name: 'Rye Whiskey' }, 'whisk')).toBe(true);
  });

  it('returns true for a substring of any alias', () => {
    expect(matchesQuery({ ...baseRow, aliases: ['rye', 'straight rye'] }, 'straight')).toBe(true);
  });

  it('is case-insensitive', () => {
    expect(matchesQuery({ ...baseRow, slug: 'rye_whiskey' }, 'RYE')).toBe(true);
  });

  it('returns true for an empty query (no filter applied)', () => {
    expect(matchesQuery({ ...baseRow }, '')).toBe(true);
  });
});

describe('neighborsOf', () => {
  it('returns focused + parents + children, all distinct', () => {
    const rows: TaxonomyViewRow[] = [
      { ...baseRow, id: 1, slug: 'whiskey',     child_ids: [2] },
      { ...baseRow, id: 2, slug: 'rye_whiskey', parent_ids: [1], child_ids: [3] },
      { ...baseRow, id: 3, slug: 'rittenhouse', parent_ids: [2], child_ids: [] },
    ];
    const byId = new Map(rows.map((r) => [r.id, r]));
    const result = neighborsOf(rows[1], byId);
    expect(result.focused.id).toBe(2);
    expect(result.parents.map((p) => p.id)).toEqual([1]);
    expect(result.children.map((c) => c.id)).toEqual([3]);
  });

  it('skips ids that are not in the byId map (defensive)', () => {
    const rows: TaxonomyViewRow[] = [
      { ...baseRow, id: 2, slug: 'rye_whiskey', parent_ids: [99], child_ids: [101] },
    ];
    const byId = new Map(rows.map((r) => [r.id, r]));
    const result = neighborsOf(rows[0], byId);
    expect(result.parents).toEqual([]);
    expect(result.children).toEqual([]);
  });
});

describe('radialPositions', () => {
  const focused = { id: 2, x: 100, y: 200 };

  it('places parents above the focused node and children below', () => {
    const positions = radialPositions(focused, [{ id: 1 }], [{ id: 3 }], 50);
    expect(positions.get(1)!.y).toBeLessThan(focused.y);
    expect(positions.get(3)!.y).toBeGreaterThan(focused.y);
  });

  it('returns positions at the requested radius (within 0.5 px)', () => {
    const positions = radialPositions(focused, [{ id: 1 }, { id: 4 }], [{ id: 3 }], 50);
    for (const id of [1, 3, 4]) {
      const p = positions.get(id)!;
      const dx = p.x - focused.x;
      const dy = p.y - focused.y;
      expect(Math.hypot(dx, dy)).toBeCloseTo(50, 0);
    }
  });

  it('is deterministic for the same input', () => {
    const a = radialPositions(focused, [{ id: 1 }, { id: 4 }], [{ id: 3 }], 50);
    const b = radialPositions(focused, [{ id: 1 }, { id: 4 }], [{ id: 3 }], 50);
    expect(Array.from(a.entries())).toEqual(Array.from(b.entries()));
  });

  it('keeps every parent strictly above the focus, even with multiple parents', () => {
    const positions = radialPositions(
      focused,
      [{ id: 1 }, { id: 2 }, { id: 4 }],
      [],
      50,
    );
    for (const id of [1, 2, 4]) {
      expect(positions.get(id)!.y).toBeLessThan(focused.y);
    }
  });

  it('does not overlap a parent and a child on the y=0 axis', () => {
    const positions = radialPositions(
      focused,
      [{ id: 1 }, { id: 2 }],
      [{ id: 3 }, { id: 4 }],
      50,
    );
    for (const id of [1, 2]) {
      expect(positions.get(id)!.y).toBeLessThan(focused.y);
    }
    for (const id of [3, 4]) {
      expect(positions.get(id)!.y).toBeGreaterThan(focused.y);
    }
  });
});

describe('rowMatchesFilters', () => {
  it('returns true when no filters are active (empty set)', () => {
    expect(rowMatchesFilters(baseRow, new Set())).toBe(true);
  });

  it('matches a role-chip via effectiveKind (kind asserted)', () => {
    const row: TaxonomyViewRow = { ...baseRow, node_kind: 'expression' };
    expect(rowMatchesFilters(row, new Set<FilterKey>(['expression']))).toBe(true);
    expect(rowMatchesFilters(row, new Set<FilterKey>(['substance']))).toBe(false);
  });

  it('AND-combines: substance + expression matches nothing', () => {
    const row: TaxonomyViewRow = { ...baseRow, node_kind: 'expression' };
    expect(rowMatchesFilters(row, new Set<FilterKey>(['substance', 'expression']))).toBe(false);
  });

  it('flag chips: cluster matches only is_cluster_node = true', () => {
    expect(rowMatchesFilters({ ...baseRow, is_cluster_node: true }, new Set<FilterKey>(['cluster']))).toBe(true);
    expect(rowMatchesFilters({ ...baseRow, is_cluster_node: false }, new Set<FilterKey>(['cluster']))).toBe(false);
  });

  it('orphan chip matches any node with no parents', () => {
    expect(rowMatchesFilters({ ...baseRow, slug: 'aperol',  parent_ids: [] }, new Set<FilterKey>(['orphan']))).toBe(true);
    expect(rowMatchesFilters({ ...baseRow, slug: 'whiskey', parent_ids: [] }, new Set<FilterKey>(['orphan']))).toBe(true);
    expect(rowMatchesFilters({ ...baseRow, slug: 'rye_whiskey', parent_ids: [1] }, new Set<FilterKey>(['orphan']))).toBe(false);
  });

  it('"no aliases" chip matches only zero-alias rows', () => {
    expect(rowMatchesFilters({ ...baseRow, aliases: [] }, new Set<FilterKey>(['no aliases']))).toBe(true);
    expect(rowMatchesFilters({ ...baseRow, aliases: ['x'] }, new Set<FilterKey>(['no aliases']))).toBe(false);
  });

  it('"zero recipes" chip matches only recipe_count === 0', () => {
    expect(rowMatchesFilters({ ...baseRow, recipe_count: 0 }, new Set<FilterKey>(['zero recipes']))).toBe(true);
    expect(rowMatchesFilters({ ...baseRow, recipe_count: 5 }, new Set<FilterKey>(['zero recipes']))).toBe(false);
  });
});
