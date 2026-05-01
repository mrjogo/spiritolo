import { describe, it, expect } from 'vitest';
import { effectiveRole, viewRowsToGraph } from './shapeData';
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
