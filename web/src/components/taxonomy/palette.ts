// Hex values mirror the CSS custom properties in taxonomy.css. Canvas
// can't read CSS vars without getComputedStyle, so the palette is
// duplicated here. Keep these in sync; Legend (Task 10+) reads from
// this module to prevent JS/CSS drift.

import type { TaxonomyRole } from './shapeData';

export const TX_GOLD        = '#c9a449';
export const TX_GOLD_DIM    = 'rgba(201, 164, 73, 0.18)';
export const TX_CLUSTER_RING = '#a85b3a';   // rust — was the prior expression fill
export const TX_NODE_BG     = '#1a0f06';
export const TX_LINK        = 'rgba(201, 164, 73, 0.55)';
export const TX_LINK_DIM    = 'rgba(201, 164, 73, 0.10)';
export const TX_FRAME_EDGE  = '#8a6a35';
export const TX_BROWN_SOFT  = '#5a3f1a';
export const TX_BROWN_INK   = '#2c1d0c';
export const TX_BROWN_MID   = '#3a2a14';
export const TX_CREAM_RGBA  = 'rgba(245, 233, 200, 0.85)'; // --tx-cream at 85% alpha
export const TX_BROWN_FAINT = '#7a5520';

export const ROLE_FILL: Record<TaxonomyRole, string> = {
  substance:  '#e8d9b0',
  expression: '#3a6b6e',                    // was #a85b3a; rust moved to TX_CLUSTER_RING
  brand:      '#7a9a82',
  unknown:    '#888888',
};

export type NodeSizeMode = 'recipes' | 'uniform';

// Matches the prior look when every node had recipe_count = 0 and clamped
// to the floor of the recipes formula.
export const UNIFORM_RADIUS = 3;

export function nodeRadius(
  node: { recipe_count: number },
  mode: NodeSizeMode = 'recipes',
): number {
  if (mode === 'uniform') return UNIFORM_RADIUS;
  return Math.max(3, Math.sqrt(node.recipe_count + 1) * 2.2);
}

// drawNode() paints the outer dark cap + gold/rust ring centered on
// nodeRadius + OUTER_RING_PAD. The ring itself is stroked at OUTER_RING_STROKE
// canvas units wide, so its visible outer edge is half a stroke past the
// centerline. Both constants are in pre-zoom canvas units; overlays scale
// the result by the current zoom factor to get on-screen pixels.
export const OUTER_RING_PAD = 2.5;
export const OUTER_RING_STROKE = 1.0;

export function outerRingRadius(
  node: { recipe_count: number },
  mode: NodeSizeMode = 'recipes',
): number {
  return nodeRadius(node, mode) + OUTER_RING_PAD + OUTER_RING_STROKE / 2;
}
