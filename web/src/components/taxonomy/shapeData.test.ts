import { describe, it, expect } from 'vitest';
import {
  effectiveRole,
  effectiveRoleLabel,
  viewRowsToGraph,
  isOrphan,
  matchesQuery,
  rowMatchesFilters,
  TOP_LEVEL_ALLOWLIST,
  neighborsOf,
  radialPositions,
} from './shapeData';
import type { FilterKey, TaxonomyViewRow } from './shapeData';

const baseRow: TaxonomyViewRow = {
  id: 1,
  slug: 'whiskey',
  display_name: 'Whiskey',
  role: null,
  role_default: 'substance',
  is_cluster_node: true,
  is_defining_garnish: false,
  parent_ids: [],
  child_ids: [2, 3],
  aliases: ['whisky'],
  recipe_count: 12,
};

describe('effectiveRole', () => {
  it('returns role when set', () => {
    expect(effectiveRole({ ...baseRow, role: 'expression', role_default: null })).toBe('expression');
  });

  it('falls back to role_default when role is null', () => {
    expect(effectiveRole({ ...baseRow, role: null, role_default: 'substance' })).toBe('substance');
  });

  it('returns "unknown" when both are null', () => {
    expect(effectiveRole({ ...baseRow, role: null, role_default: null })).toBe('unknown');
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
});

describe('TOP_LEVEL_ALLOWLIST', () => {
  it('includes the canonical roots of the DAG', () => {
    expect(TOP_LEVEL_ALLOWLIST).toEqual(
      expect.arrayContaining([
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
        'syrup',
        'mixer',
      ]),
    );
  });
});

describe('isOrphan', () => {
  it('flags a node with no parents that is not on the allowlist', () => {
    expect(isOrphan({ ...baseRow, slug: 'aperol', parent_ids: [] })).toBe(true);
  });

  it('does not flag a node with no parents that is on the allowlist', () => {
    expect(isOrphan({ ...baseRow, slug: 'whiskey', parent_ids: [] })).toBe(false);
  });

  it('does not flag a node that has parents', () => {
    expect(isOrphan({ ...baseRow, slug: 'rye_whiskey', parent_ids: [1] })).toBe(false);
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

describe('effectiveRoleLabel', () => {
  it('returns the asserted role unchanged when set', () => {
    expect(effectiveRoleLabel({ ...baseRow, role: 'expression', role_default: null })).toBe('expression');
  });

  it('marks the inferred role with a trailing ? when only role_default is set', () => {
    expect(effectiveRoleLabel({ ...baseRow, role: null, role_default: 'substance' })).toBe('substance?');
  });

  it('returns "unknown" when both are null', () => {
    expect(effectiveRoleLabel({ ...baseRow, role: null, role_default: null })).toBe('unknown');
  });
});

describe('rowMatchesFilters', () => {
  it('returns true when no filters are active (empty set)', () => {
    expect(rowMatchesFilters(baseRow, new Set())).toBe(true);
  });

  it('matches a role-chip via effectiveRole (substance via role_default fallback)', () => {
    const row = { ...baseRow, role: null, role_default: 'substance' as const };
    expect(rowMatchesFilters(row, new Set<FilterKey>(['substance']))).toBe(true);
    expect(rowMatchesFilters(row, new Set<FilterKey>(['expression']))).toBe(false);
  });

  it('AND-combines: substance + expression matches nothing', () => {
    const row = { ...baseRow, role: null, role_default: 'substance' as const };
    expect(rowMatchesFilters(row, new Set<FilterKey>(['substance', 'expression']))).toBe(false);
  });

  it('flag chips: cluster matches only is_cluster_node = true', () => {
    expect(rowMatchesFilters({ ...baseRow, is_cluster_node: true }, new Set<FilterKey>(['cluster']))).toBe(true);
    expect(rowMatchesFilters({ ...baseRow, is_cluster_node: false }, new Set<FilterKey>(['cluster']))).toBe(false);
  });

  it('orphan chip uses isOrphan (no parents AND not on allowlist)', () => {
    expect(rowMatchesFilters({ ...baseRow, slug: 'aperol', parent_ids: [] }, new Set<FilterKey>(['orphan']))).toBe(true);
    expect(rowMatchesFilters({ ...baseRow, slug: 'whiskey', parent_ids: [] }, new Set<FilterKey>(['orphan']))).toBe(false);
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
