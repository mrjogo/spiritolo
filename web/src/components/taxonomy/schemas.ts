import { z } from 'zod';

// Allowed default_role values, derived from the role classifier in
// ingredients/src/ingredients/dedup/cluster.py + role_classifier.py.
export const DEFAULT_ROLE_OPTIONS = [
  'base_spirit',
  'modifier',
  'bitters',
  'citrus',
  'sweetener',
  'dilution',
  'wash',
  'garnish',
  'other',
] as const;

export const NODE_KIND_OPTIONS = ['brand', 'expression'] as const;

const slugSchema = z
  .string()
  .min(1, 'slug required')
  .regex(/^[a-z0-9_]+$/, 'slug must be lowercase letters, digits, underscores');

const displayNameSchema = z.string().min(1, 'display name required');
const aliasArraySchema = z.array(z.string().min(1)).default([]);

export const createChildSchema = z.object({
  display_name: displayNameSchema,
  slug: slugSchema,
  node_kind: z.enum(NODE_KIND_OPTIONS).nullable(),
  default_role: z.enum(DEFAULT_ROLE_OPTIONS).nullable(),
  is_cluster_node: z.boolean(),
  is_defining_garnish: z.boolean(),
  aliases: aliasArraySchema,
});
export type CreateChildInput = z.infer<typeof createChildSchema>;

// Inline-edit schemas — one per editor type. RHF forms use these per row.
export const updateDisplayNameSchema = z.object({ display_name: displayNameSchema });
export const updateSlugSchema = z.object({ slug: slugSchema });
export const updateNodeKindSchema = z.object({
  node_kind: z.enum(NODE_KIND_OPTIONS).nullable(),
});
export const updateDefaultRoleSchema = z.object({
  default_role: z.enum(DEFAULT_ROLE_OPTIONS).nullable(),
});
export const updateBoolSchema = z.object({ value: z.boolean() });
export const updateAliasesSchema = z.object({ aliases: aliasArraySchema });

export const setNodeParentsSchema = z.object({
  parent_ids: z.array(z.number().int().positive()),
});

// Slug auto-derivation from display name.
export function deriveSlug(displayName: string): string {
  return displayName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}
