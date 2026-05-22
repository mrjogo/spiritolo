import { supabase } from '../../supabase';

export class RpcError extends Error {
  readonly cause: unknown;
  constructor(message: string, cause: unknown) {
    super(message);
    this.cause = cause;
    this.name = 'RpcError';
  }
}

export async function applyProposalCreate(
  proposalId: number,
  slugOverride: string | null,
): Promise<number> {
  const { data, error } = await supabase.rpc('apply_proposal_create', {
    p_proposal_id: proposalId,
    p_slug_override: slugOverride,
  });
  if (error) throw new RpcError(`apply_proposal_create: ${error.message}`, error);
  if (typeof data !== 'number') {
    throw new RpcError('apply_proposal_create: expected number response', data);
  }
  return data;
}

export async function applyProposalMapToExisting(
  proposalId: number,
  nodeId: number,
): Promise<void> {
  const { error } = await supabase.rpc('apply_proposal_map_to_existing', {
    p_proposal_id: proposalId,
    p_node_id: nodeId,
  });
  if (error) throw new RpcError(`apply_proposal_map_to_existing: ${error.message}`, error);
}

export async function applyProposalFlag(
  proposalId: number,
  reason: string,
): Promise<void> {
  const { error } = await supabase.rpc('apply_proposal_flag', {
    p_proposal_id: proposalId,
    p_reason: reason,
  });
  if (error) throw new RpcError(`apply_proposal_flag: ${error.message}`, error);
}
