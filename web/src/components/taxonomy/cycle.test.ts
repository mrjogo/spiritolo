import { describe, it, expect } from 'vitest';
import { descendantsOf } from './cycle';
import type { TaxonomyViewRow } from './shapeData';

function row(id: number, child_ids: number[] = []): TaxonomyViewRow {
  return {
    id, slug: `n${id}`, display_name: `N${id}`,
    node_kind: null, default_role: null,
    is_cluster_node: false, is_defining_garnish: false,
    parent_ids: [], child_ids, aliases: [], recipe_count: 0,
  };
}

describe('descendantsOf', () => {
  it('returns empty set for leaf node', () => {
    const rows = [row(1), row(2)];
    expect(descendantsOf(1, rows)).toEqual(new Set());
  });

  it('returns immediate children', () => {
    const rows = [row(1, [2, 3]), row(2), row(3)];
    expect(descendantsOf(1, rows)).toEqual(new Set([2, 3]));
  });

  it('returns transitive descendants', () => {
    const rows = [row(1, [2]), row(2, [3]), row(3, [4]), row(4)];
    expect(descendantsOf(1, rows)).toEqual(new Set([2, 3, 4]));
  });

  it('handles diamond (descendant reachable via two paths)', () => {
    const rows = [row(1, [2, 3]), row(2, [4]), row(3, [4]), row(4)];
    expect(descendantsOf(1, rows)).toEqual(new Set([2, 3, 4]));
  });

  it('does not include the seed node itself', () => {
    const rows = [row(1, [2]), row(2, [1])]; // would-be cycle in data; defensive
    const got = descendantsOf(1, rows);
    expect(got.has(1)).toBe(false);
    expect(got.has(2)).toBe(true);
  });
});
