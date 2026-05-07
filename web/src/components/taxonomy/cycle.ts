import type { TaxonomyViewRow } from './shapeData';

/**
 * Walk child_ids transitively from `seedId` and return the set of
 * descendants (excluding the seed). Used by the parent-edit overlay
 * to grey out nodes that would create a cycle if added as a parent.
 *
 * Defensive against pre-existing cycles in the data: we mark visited
 * ids and stop walking through them, so a malformed graph doesn't
 * loop forever.
 */
export function descendantsOf(seedId: number, rows: TaxonomyViewRow[]): Set<number> {
  const byId = new Map(rows.map((r) => [r.id, r]));
  const out = new Set<number>();
  const stack: number[] = [seedId];
  const seen = new Set<number>([seedId]);
  while (stack.length > 0) {
    const cur = stack.pop()!;
    const node = byId.get(cur);
    if (!node) continue;
    for (const childId of node.child_ids) {
      if (seen.has(childId)) continue;
      seen.add(childId);
      out.add(childId);
      stack.push(childId);
    }
  }
  return out;
}
