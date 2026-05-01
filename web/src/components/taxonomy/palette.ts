// Hex values mirror the CSS custom properties in taxonomy.css. Canvas
// can't read CSS vars without getComputedStyle, so the palette is
// duplicated here. Keep these in sync; Legend (Task 10+) reads from
// this module to prevent JS/CSS drift.

import type { TaxonomyRole } from './shapeData';

export const TX_GOLD        = '#c9a449';
export const TX_NODE_BG     = '#1a0f06';
export const TX_ORPHAN_RING = '#a85b3a';
export const TX_LINK        = 'rgba(201, 164, 73, 0.55)';
export const TX_FRAME_EDGE  = '#8a6a35';
export const TX_BROWN_SOFT  = '#5a3f1a';
export const TX_BROWN_INK   = '#2c1d0c';
export const TX_BROWN_MID   = '#3a2a14';

export const ROLE_FILL: Record<TaxonomyRole, string> = {
  substance:  '#e8d9b0',
  expression: '#a85b3a',
  brand:      '#7a9a82',
  unknown:    '#888888',
};

export function nodeRadius(node: { recipe_count: number }): number {
  return Math.max(3, Math.sqrt(node.recipe_count + 1) * 2.2);
}
