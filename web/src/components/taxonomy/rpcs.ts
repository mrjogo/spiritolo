import { supabase } from '../../supabase';
import type { CreateChildInput } from './schemas';

export type TaxonomyBlockers = {
  children: number;
  child_names: { id: number; display_name: string }[];
  parents: number;
  aliases: number;
  provenance: number;
  recipe_ingredients: number;
  form_proposals: number;
};

export class RpcError extends Error {
  readonly cause: unknown;
  constructor(message: string, cause: unknown) {
    super(message);
    this.cause = cause;
    this.name = 'RpcError';
  }
}

export function unwrap<T>(data: T | null, error: { message: string } | null, op: string): T {
  if (error) throw new RpcError(`${op}: ${error.message}`, error);
  if (data === null) throw new RpcError(`${op}: empty response`, null);
  return data;
}

export async function getTaxonomyNodeBlockers(id: number): Promise<TaxonomyBlockers> {
  const { data, error } = await supabase.rpc('get_taxonomy_node_blockers', { p_id: id });
  return unwrap<TaxonomyBlockers>(data as TaxonomyBlockers, error, 'get_taxonomy_node_blockers');
}

export async function createTaxonomyNode(parentId: number, input: CreateChildInput): Promise<number> {
  const { data, error } = await supabase.rpc('create_taxonomy_node', {
    p_parent_id: parentId,
    p_slug: input.slug,
    p_display_name: input.display_name,
    p_node_kind: input.node_kind,
    p_default_role: input.default_role,
    p_is_cluster_node: input.is_cluster_node,
    p_is_defining_garnish: input.is_defining_garnish,
    p_aliases: input.aliases,
  });
  return unwrap<number>(data as number, error, 'create_taxonomy_node');
}

// Patch may contain any subset of: slug, display_name, node_kind,
// default_role, is_cluster_node, is_defining_garnish, aliases.
export async function updateTaxonomyNode(
  id: number,
  patch: Record<string, unknown>,
): Promise<void> {
  const { error } = await supabase.rpc('update_taxonomy_node', {
    p_id: id,
    p_patch: patch,
  });
  if (error) throw new RpcError(`update_taxonomy_node: ${error.message}`, error);
}

export async function setNodeParents(id: number, parentIds: number[]): Promise<void> {
  const { error } = await supabase.rpc('set_node_parents', {
    p_id: id,
    p_parent_ids: parentIds,
  });
  if (error) throw new RpcError(`set_node_parents: ${error.message}`, error);
}

export async function deleteTaxonomyNode(id: number): Promise<void> {
  const { error } = await supabase.rpc('delete_taxonomy_node', { p_id: id });
  if (error) throw new RpcError(`delete_taxonomy_node: ${error.message}`, error);
}
