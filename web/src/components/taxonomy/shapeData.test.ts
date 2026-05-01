import { describe, it, expect } from 'vitest';
import { effectiveRole, viewRowsToGraph, isOrphan, matchesQuery, TOP_LEVEL_ALLOWLIST } from './shapeData';
import type { TaxonomyViewRow } from './shapeData';

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
