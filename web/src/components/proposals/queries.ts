import { useQuery, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../supabase';
import {
  pendingProposalSchema, parentBucketSchema,
  type PendingProposal, type ParentBucket,
} from './schemas';

export const proposalsQueryKey = () => ['proposals', 'pending'] as const;
export const parentsQueryKey = () => ['proposals', 'parents'] as const;
export const flagReasonsQueryKey = () => ['flagReasons'] as const;

async function fetchPendingProposals(): Promise<PendingProposal[]> {
  const { data, error } = await supabase
    .from('pending_proposals_view')
    .select('*')
    .order('created_at', { ascending: false });
  if (error) throw error;
  return (data ?? []).map((r) => pendingProposalSchema.parse(r));
}

async function fetchParents(): Promise<ParentBucket[]> {
  const { data, error } = await supabase
    .from('pending_proposals_parents_view')
    .select('*')
    .order('pending_count', { ascending: false });
  if (error) throw error;
  return (data ?? []).map((r) => parentBucketSchema.parse(r));
}

async function fetchFlagReasons(): Promise<string[]> {
  // RLS already gates recipe_ingredients to admins (admin_read policy).
  const { data, error } = await supabase
    .from('recipe_ingredients')
    .select('flag_reason')
    .not('flag_reason', 'is', null);
  if (error) throw error;
  const set = new Set<string>();
  for (const row of data ?? []) {
    const v = (row as { flag_reason: string | null }).flag_reason;
    if (v) set.add(v);
  }
  return [...set].sort();
}

export function usePendingProposals() {
  return useQuery({
    queryKey: proposalsQueryKey(),
    queryFn: fetchPendingProposals,
  });
}

export function usePendingParents() {
  return useQuery({
    queryKey: parentsQueryKey(),
    queryFn: fetchParents,
  });
}

export function useFlagReasons() {
  return useQuery({
    queryKey: flagReasonsQueryKey(),
    queryFn: fetchFlagReasons,
  });
}

// Call after any apply_proposal_* RPC succeeds; refetches both views
// + the flag-reason autosuggest pool.
export function useInvalidateProposalQueries() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: proposalsQueryKey() });
    qc.invalidateQueries({ queryKey: parentsQueryKey() });
    qc.invalidateQueries({ queryKey: flagReasonsQueryKey() });
  };
}
