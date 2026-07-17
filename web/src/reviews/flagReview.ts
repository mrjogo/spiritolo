import { supabase } from '../supabase';

// Thin typed clients over the two review RPCs. Follows the taxonomy rpcs.ts
// convention: named p_ args, throw the PostgREST error on failure. These are
// the shared contract other reviews UI (FlagButton, ReviewCard) calls into.

export interface FlagReviewArgs {
  entityKind: string;
  entityId: string;
  stage: string;
  note?: string;
}

// Open a human_flag review; resolves to the new stage_reviews.id (bigint).
export async function flagReview(a: FlagReviewArgs): Promise<number> {
  const { data, error } = await supabase.rpc('flag_review', {
    p_entity_kind: a.entityKind,
    p_entity_id: a.entityId,
    p_stage: a.stage,
    p_note: a.note ?? null,
  });
  if (error) throw error;
  return data as number;
}

export interface ResolveReviewArgs {
  id: number;
  payload?: unknown;
}

// Resolve a review, attaching an optional payload (jsonb) that records the fix.
export async function resolveReview(a: ResolveReviewArgs): Promise<void> {
  const { error } = await supabase.rpc('resolve_review', {
    p_id: a.id,
    p_payload: a.payload ?? null,
  });
  if (error) throw error;
}

// Dismiss a review (no fix applied) — same RPC, p_dismiss flag flips the state.
export async function dismissReview(id: number): Promise<void> {
  const { error } = await supabase.rpc('resolve_review', {
    p_id: id,
    p_dismiss: true,
  });
  if (error) throw error;
}
