import { useState } from 'react';
import type { ComponentType } from 'react';
import { resolveReview, dismissReview } from '../../reviews/flagReview';
import { CrossLink, reviewEntityHref } from '../../ui/opsLinks';
import { MapReviewBody } from './bodies/MapReviewBody';
import { ParseReviewBody } from './bodies/ParseReviewBody';

// Mirrors a `human_reviews` row (the committed DB surface). Owned here because
// the card and its per-stage bodies all key off this shape.
export interface StageReview {
  id: number;
  entity_kind: string;
  entity_id: string;
  stage: string;
  state: 'open' | 'resolved' | 'dismissed';
  origin: 'human_flag' | 'machine_proposal' | 'distance_gate';
  payload: unknown | null;
  note: string | null;
}

// Per-stage read-only summary bodies, keyed by `human_reviews.stage`. A stage
// without a registered body just shows the editable payload below.
const BODIES: Record<string, ComponentType<{ review: StageReview }>> = {
  'map-ingredient': MapReviewBody,
  'parse-ingredients': ParseReviewBody,
};

// What Resolve writes: the payload is applied by the SQL apply_review() per
// stage (map-ingredient -> resolution slug, parse-ingredients -> ingredient
// fields, etc.). The editor
// is a raw JSON textarea so a curator can author the fix for ANY stage today;
// structured per-stage edit forms are a follow-up. Approving a form proposal
// (which must CREATE a node) is not wired through this editor — dismiss those
// here and use the curation flow.
export function ReviewCard({
  review,
  onActed,
}: {
  review: StageReview;
  onActed?: () => void;
}) {
  const Body = BODIES[review.stage];
  const [payloadText, setPayloadText] = useState(() =>
    JSON.stringify(review.payload ?? {}, null, 2),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function parsePayload(): unknown | undefined {
    try {
      return payloadText.trim() === '' ? {} : JSON.parse(payloadText);
    } catch {
      setError('Payload is not valid JSON');
      return undefined;
    }
  }

  async function onResolve() {
    setError(null);
    const payload = parsePayload();
    if (payload === undefined) return;
    setBusy(true);
    try {
      await resolveReview({ id: review.id, payload });
      onActed?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Resolve failed');
    } finally {
      setBusy(false);
    }
  }

  async function onDismiss() {
    setError(null);
    setBusy(true);
    try {
      await dismissReview(review.id);
      onActed?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Dismiss failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="review-card"
      style={{
        border: '1px solid var(--ops-border, #e3e5e9)',
        borderRadius: 6,
        padding: 12,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', fontSize: 12 }}>
        <span className="review-card__origin" style={{ fontFamily: 'monospace', opacity: 0.8 }}>
          {review.origin}
        </span>
        <span className="review-card__stage" style={{ opacity: 0.6 }}>
          {review.stage}
        </span>
        <span className="review-card__entity" style={{ fontFamily: 'monospace', opacity: 0.6 }}>
          {review.entity_kind}:
          {(() => {
            const href = reviewEntityHref(review.entity_kind, review.entity_id);
            return href ? (
              <CrossLink to={href}>{review.entity_id}</CrossLink>
            ) : (
              review.entity_id
            );
          })()}
        </span>
      </div>

      {review.note && (
        <p className="review-card__note" style={{ margin: 0 }}>
          {review.note}
        </p>
      )}

      {Body && (
        <div className="review-card__body">
          <Body review={review} />
        </div>
      )}

      <label style={{ fontSize: 11, opacity: 0.7 }}>
        Fix (payload JSON)
        {/* Sizing (width / monospace / font-size / margin) lives in
            `.ops .review-card textarea` in ops.css so the mobile stylesheet can
            bump it to 16px and dodge iOS Safari's focus-zoom. */}
        <textarea
          aria-label="payload JSON"
          value={payloadText}
          onChange={(e) => setPayloadText(e.target.value)}
          spellCheck={false}
          rows={Math.min(8, payloadText.split('\n').length + 1)}
        />
      </label>

      {error && (
        <p role="alert" style={{ margin: 0, color: 'var(--danger, #b00020)', fontSize: 12 }}>
          {error}
        </p>
      )}

      <div className="review-card__actions" style={{ display: 'flex', gap: 8 }}>
        <button type="button" disabled={busy} onClick={() => void onResolve()}>
          Resolve
        </button>
        <button type="button" disabled={busy} onClick={() => void onDismiss()}>
          Dismiss
        </button>
      </div>
    </div>
  );
}
