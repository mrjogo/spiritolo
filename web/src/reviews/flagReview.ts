import { api } from '../api';

// Thin typed clients over the review endpoints. These are the shared contract
// the reviews UI (FlagButton, ReviewCard) calls into.

export interface FlagReviewArgs {
  entityKind: string;
  entityId: string;
  stage: string;
  note?: string;
}

// Open a human_flag review; resolves to the human_reviews.id.
export async function flagReview(a: FlagReviewArgs): Promise<number> {
  const res = await api<{ id: number }>('/api/ops/reviews/flag', {
    body: { entity_kind: a.entityKind, entity_id: a.entityId, stage: a.stage, note: a.note ?? null },
  });
  return res.id;
}

export interface ResolveReviewArgs {
  id: number;
  payload?: unknown;
}

// Resolve a review, attaching an optional payload that records the fix.
export async function resolveReview(a: ResolveReviewArgs): Promise<void> {
  await api(`/api/ops/reviews/${a.id}/resolve`, { body: { payload: a.payload ?? null } });
}

// Dismiss a review (no fix applied).
export async function dismissReview(id: number): Promise<void> {
  await api(`/api/ops/reviews/${id}/dismiss`, { method: 'POST' });
}
