import { z } from 'zod';

// Mirrors the kebab-case CHECK on taxonomy_proposals.proposed_slug.
export const slugSchema = z
  .string()
  .min(1, 'slug required')
  .regex(
    /^[a-z0-9][a-z0-9-]*$/,
    'slug must be kebab-case (lowercase letters, digits, dashes; must start with a letter or digit)',
  );

export const slugFormSchema = z.object({ slug: slugSchema });
export type SlugFormInput = z.infer<typeof slugFormSchema>;

export const flagFormSchema = z.object({
  reason: z.string().trim().min(1, 'reason required'),
});
export type FlagFormInput = z.infer<typeof flagFormSchema>;

// Shape of one entry in taxonomy_proposals.candidates jsonb.
export const candidateSchema = z.object({
  node_id: z.number().int(),
  display_name: z.string(),
  similarity: z.number(),
});
export type Candidate = z.infer<typeof candidateSchema>;

export const pendingProposalSchema = z.object({
  id: z.number().int(),
  raw_string: z.string(),
  proposed_slug: z.string(),
  proposed_display_name: z.string().nullable(),
  proposed_parent_id: z.number().int().nullable(),
  proposed_parent_display_name: z.string().nullable(),
  candidates: z.array(candidateSchema),
  mapper_version: z.string(),
  created_at: z.string(),
});
export type PendingProposal = z.infer<typeof pendingProposalSchema>;

export const parentBucketSchema = z.object({
  proposed_parent_id: z.number().int().nullable(),
  proposed_parent_display_name: z.string().nullable(),
  pending_count: z.number().int(),
});
export type ParentBucket = z.infer<typeof parentBucketSchema>;
