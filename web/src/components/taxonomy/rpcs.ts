import { api, ApiError } from '../../api';
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

// The error every taxonomy curation call throws. Kept under its historical
// name for the components that catch it; it is the shared API error.
export { ApiError as RpcError };

export function getTaxonomyNodeBlockers(id: number): Promise<TaxonomyBlockers> {
  return api<TaxonomyBlockers>(`/api/ops/taxonomy/nodes/${id}/blockers`);
}

export async function createTaxonomyNode(parentId: number, input: CreateChildInput): Promise<number> {
  const res = await api<{ id: number }>('/api/ops/taxonomy/nodes', {
    body: {
      parent_id: parentId,
      slug: input.slug,
      display_name: input.display_name,
      node_kind: input.node_kind,
      default_role: input.default_role,
      is_cluster_node: input.is_cluster_node,
      is_defining_garnish: input.is_defining_garnish,
      aliases: input.aliases,
    },
  });
  return res.id;
}

// Patch may contain any subset of: slug, display_name, node_kind,
// default_role, is_cluster_node, is_defining_garnish, aliases.
export async function updateTaxonomyNode(id: number, patch: Record<string, unknown>): Promise<void> {
  await api(`/api/ops/taxonomy/nodes/${id}`, { method: 'PATCH', body: { patch } });
}

export async function setNodeParents(id: number, parentIds: number[]): Promise<void> {
  await api(`/api/ops/taxonomy/nodes/${id}/parents`, { method: 'PUT', body: { parent_ids: parentIds } });
}

export async function deleteTaxonomyNode(id: number): Promise<void> {
  await api(`/api/ops/taxonomy/nodes/${id}`, { method: 'DELETE' });
}
